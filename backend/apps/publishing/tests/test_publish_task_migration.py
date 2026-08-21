import io
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


MIGRATE_FROM = [("publishing", "0005_publishattempt_provider_call_started_at_and_more")]
MIGRATE_TO = [("publishing", "0006_publishtask_unique_live_content_account")]
LATEST = [("publishing", "0010_publishreconciliationattempt_candidate_search_truncated")]


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate(target)
    return executor.loader.project_state(target).apps


def _create_task(apps, context, *, status, key, submission_id=""):
    PublishTask = apps.get_model("publishing", "PublishTask")
    return PublishTask.objects.create(
        organization_id=context["organization"].id,
        platform_content_id=context["content"].id,
        content_version=context["content"].version,
        social_account_id=context["account"].id,
        platform_id=context["platform"].id,
        connector_code="buffer",
        idempotency_key=key,
        request_fingerprint=f"fingerprint-{key}",
        status=status,
        provider_submission_id=submission_id,
        created_by_id=context["actor"].id,
    )


def _create_attempt(apps, context, task, *, status, submission_id=""):
    PublishAttempt = apps.get_model("publishing", "PublishAttempt")
    return PublishAttempt.objects.create(
        organization_id=context["organization"].id,
        task_id=task.id,
        number=1,
        claim_token=uuid.uuid4(),
        status=status,
        request_fingerprint=task.request_fingerprint,
        outcome=status,
        external_id="",
        provider_submission_id=submission_id,
        started_at=timezone.now(),
    )


def _cleanup_and_restore(task_ids):
    old_apps = MigrationExecutor(connection).loader.project_state(MIGRATE_FROM).apps
    PublishAttempt = old_apps.get_model("publishing", "PublishAttempt")
    PublishTask = old_apps.get_model("publishing", "PublishTask")
    PublishAttempt.objects.filter(task_id__in=task_ids).delete()
    PublishTask.objects.filter(id__in=task_ids).delete()
    _migrate(LATEST)


@pytest.mark.django_db(transaction=True)
def test_unique_constraint_migration_preserves_clean_existing_task(publishing_context):
    old_apps = _migrate(MIGRATE_FROM)
    task = _create_task(
        old_apps,
        publishing_context,
        status="SUBMITTED",
        key="migration-clean",
        submission_id="buffer-post-clean",
    )
    task_ids = [task.id]
    try:
        new_apps = _migrate(MIGRATE_TO)
        migrated = new_apps.get_model("publishing", "PublishTask").objects.get(id=task.id)
        assert migrated.status == "SUBMITTED"
        assert migrated.provider_submission_id == "buffer-post-clean"
    finally:
        _migrate(MIGRATE_FROM)
        _cleanup_and_restore(task_ids)


@pytest.mark.django_db(transaction=True)
def test_unique_constraint_migration_blocks_duplicates_without_modifying_history(
    publishing_context,
):
    old_apps = _migrate(MIGRATE_FROM)
    first = _create_task(
        old_apps,
        publishing_context,
        status="SUBMITTED",
        key="migration-duplicate-a",
        submission_id="buffer-post-a",
    )
    second = _create_task(
        old_apps,
        publishing_context,
        status="SUBMISSION_UNKNOWN",
        key="migration-duplicate-b",
    )
    first_attempt = _create_attempt(
        old_apps,
        publishing_context,
        first,
        status="SUBMITTED",
        submission_id="buffer-post-a",
    )
    second_attempt = _create_attempt(
        old_apps,
        publishing_context,
        second,
        status="SUBMISSION_UNKNOWN",
    )
    task_ids = [first.id, second.id]
    PublishTask = old_apps.get_model("publishing", "PublishTask")
    PublishAttempt = old_apps.get_model("publishing", "PublishAttempt")
    tasks_before = list(
        PublishTask.objects.filter(id__in=task_ids)
        .order_by("id")
        .values("id", "status", "provider_submission_id", "last_error")
    )
    attempts_before = list(
        PublishAttempt.objects.filter(id__in=[first_attempt.id, second_attempt.id])
        .order_by("id")
        .values("id", "task_id", "status", "provider_submission_id", "error")
    )
    try:
        with pytest.raises(RuntimeError) as exc_info:
            _migrate(MIGRATE_TO)

        message = str(exc_info.value)
        assert "audit_duplicate_publish_tasks" in message
        assert str(first.id) in message
        assert str(second.id) in message
        assert "SUBMITTED" in message
        assert "SUBMISSION_UNKNOWN" in message
        assert "buffer-post-a" not in message
        assert list(
            PublishTask.objects.filter(id__in=task_ids).order_by("id").values(
                "id", "status", "provider_submission_id", "last_error"
            )
        ) == tasks_before
        assert list(
            PublishAttempt.objects.filter(id__in=[first_attempt.id, second_attempt.id])
            .order_by("id")
            .values("id", "task_id", "status", "provider_submission_id", "error")
        ) == attempts_before
    finally:
        _cleanup_and_restore(task_ids)


@pytest.mark.django_db(transaction=True)
def test_duplicate_audit_command_is_read_only_and_sanitized(publishing_context):
    old_apps = _migrate(MIGRATE_FROM)
    first = _create_task(
        old_apps,
        publishing_context,
        status="RUNNING",
        key="audit-duplicate-a",
        submission_id="secret-submission-id",
    )
    second = _create_task(
        old_apps,
        publishing_context,
        status="SUBMISSION_UNKNOWN",
        key="audit-duplicate-b",
    )
    task_ids = [first.id, second.id]
    PublishTask = old_apps.get_model("publishing", "PublishTask")
    before = list(
        PublishTask.objects.filter(id__in=task_ids)
        .order_by("id")
        .values("id", "status", "provider_submission_id")
    )
    output = io.StringIO()
    try:
        with pytest.raises(CommandError, match="duplicate live publish task group"):
            call_command("audit_duplicate_publish_tasks", stdout=output)

        report = output.getvalue()
        assert str(first.id) in report
        assert str(second.id) in report
        assert "RUNNING" in report
        assert "SUBMISSION_UNKNOWN" in report
        assert "secret-submission-id" not in report
        assert list(
            PublishTask.objects.filter(id__in=task_ids)
            .order_by("id")
            .values("id", "status", "provider_submission_id")
        ) == before
    finally:
        _cleanup_and_restore(task_ids)
