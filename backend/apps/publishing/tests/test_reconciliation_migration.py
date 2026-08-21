import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


MIGRATE_FROM = [("publishing", "0006_publishtask_unique_live_content_account")]
MIGRATE_TO = [("publishing", "0007_publishreconciliationattempt_and_more")]
LATEST = [("publishing", "0010_publishreconciliationattempt_candidate_search_truncated")]


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate(target)
    return executor.loader.project_state(target).apps


def _task(apps, context, *, status, key):
    return apps.get_model("publishing", "PublishTask").objects.create(
        organization_id=context["organization"].id,
        platform_content_id=context["content"].id,
        content_version=context["content"].version,
        social_account_id=context["account"].id,
        platform_id=context["platform"].id,
        connector_code="mock",
        idempotency_key=key,
        request_fingerprint=f"migration-{key}",
        status=status,
        created_by_id=context["actor"].id,
    )


@pytest.mark.django_db(transaction=True)
def test_reconciliation_migration_preserves_existing_history(publishing_context):
    old_apps = _migrate(MIGRATE_FROM)
    task = _task(old_apps, publishing_context, status="SUBMITTED", key="d1-clean")
    try:
        new_apps = _migrate(MIGRATE_TO)
        migrated = new_apps.get_model("publishing", "PublishTask").objects.get(pk=task.pk)
        assert migrated.status == "SUBMITTED"
        assert migrated.reconciliation_attempt_number == 0
        assert migrated.next_reconcile_at is None
    finally:
        _migrate(MIGRATE_FROM)
        old_apps.get_model("publishing", "PublishTask").objects.filter(pk=task.pk).delete()
        _migrate(LATEST)


@pytest.mark.django_db(transaction=True)
def test_reconciliation_migration_blocks_newly_protected_duplicates_without_changes(
    publishing_context,
):
    old_apps = _migrate(MIGRATE_FROM)
    first = _task(old_apps, publishing_context, status="NEEDS_ATTENTION", key="d1-a")
    second = _task(old_apps, publishing_context, status="NEEDS_ATTENTION", key="d1-b")
    Task = old_apps.get_model("publishing", "PublishTask")
    before = list(Task.objects.filter(pk__in=[first.pk, second.pk]).values("id", "status"))
    try:
        with pytest.raises(RuntimeError) as exc_info:
            _migrate(MIGRATE_TO)
        message = str(exc_info.value)
        assert str(first.pk) in message
        assert str(second.pk) in message
        assert "NEEDS_ATTENTION" in message
        assert list(Task.objects.filter(pk__in=[first.pk, second.pk]).values("id", "status")) == before
    finally:
        Task.objects.filter(pk__in=[first.pk, second.pk]).delete()
        _migrate(LATEST)
