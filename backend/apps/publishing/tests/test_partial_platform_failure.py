import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.content.models import content_writes
from apps.content.services import create_platform_revision
from apps.publishing.models import (
    PublishAttempt, PublishedPost, PublishTask, publishing_writes,
)
from apps.publishing.services import (
    PublishingConflict, cancel_publish_task, create_publish_task,
    claim_publish_task, complete_publish_success, enqueue_due_publish_tasks,
    execute_publish_task, retry_publish_task,
)
from apps.platforms.models import PlatformCapability, SocialAccount
from integrations.platforms.base import PublishResult


def _task(context, key, *, scheduled=False, account=None):
    return create_publish_task(
        content=context["content"],
        account=account or context["account"],
        idempotency_key=key,
        scheduled_at=timezone.now() + timedelta(hours=1) if scheduled else None,
        actor=context["actor"],
    )


def test_mock_success_is_atomic_and_duplicate_delivery_is_idempotent(
    publishing_context,
):
    context = publishing_context
    task = _task(context, "success")

    first = execute_publish_task(task.id)
    duplicate = execute_publish_task(task.id)

    task.refresh_from_db()
    context["content"].refresh_from_db()
    assert first.pk == duplicate.pk
    assert first.external_id == f"mock-{task.id}"
    assert task.status == PublishTask.Status.SUCCEEDED
    assert context["content"].status == PlatformContent.Status.PUBLISHED
    assert PublishAttempt.objects.filter(task=task).count() == 1
    assert PublishedPost.objects.filter(task=task).count() == 1


@pytest.mark.parametrize(
    ("outcome", "error_code", "retryable"),
    [
        ("token_expired", "TOKEN_EXPIRED", False),
        ("rate_limit", "RATE_LIMITED", True),
        ("provider_error", "PROVIDER_ERROR", True),
    ],
)
def test_connector_failures_are_safe_and_retry_policy_is_explicit(
    publishing_context, outcome, error_code, retryable,
):
    context = publishing_context
    account = context["account"]
    account.connector_metadata = {"mock_outcome": outcome}
    account.save(update_fields=["connector_metadata", "updated_at"])
    task = _task(context, outcome)

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    context["content"].refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == error_code
    assert attempt.error["code"] == error_code
    assert not PublishedPost.objects.filter(task=task).exists()
    assert context["content"].status == PlatformContent.Status.APPROVED
    if retryable:
        if task.retry_not_before:
            task.retry_not_before = timezone.now() - timedelta(seconds=1)
            from apps.publishing.models import publishing_writes
            with publishing_writes():
                task.save(update_fields=["retry_not_before", "updated_at"])
        assert retry_publish_task(task, actor=context["actor"]).status == "QUEUED"
    else:
        with pytest.raises(PublishingConflict, match="token"):
            retry_publish_task(task, actor=context["actor"])


def test_mock_fail_once_supports_visible_failure_then_successful_retry(publishing_context):
    context = publishing_context
    account = context["account"]
    account.connector_metadata = {"mock_outcome": "fail_once"}
    account.save(update_fields=["connector_metadata", "updated_at"])
    task = _task(context, "fail-once")

    assert execute_publish_task(task.id) is None
    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error == {
        "code": "PROVIDER_ERROR",
        "message": "Provider rejected the publish request.",
    }

    # A retry may execute in a fresh worker with no process-local connector memory.
    import importlib
    from integrations.platforms import mock
    importlib.reload(mock)
    retry_publish_task(task, actor=context["actor"])
    post = execute_publish_task(task.id)
    task.refresh_from_db()
    assert post is not None
    assert task.status == PublishTask.Status.SUCCEEDED
    assert list(task.attempts.values_list("status", flat=True)) == [
        PublishAttempt.Status.FAILED,
        PublishAttempt.Status.SUCCEEDED,
    ]


def test_canceled_task_never_calls_connector(publishing_context, monkeypatch):
    context = publishing_context
    task = _task(context, "cancel")
    cancel_publish_task(task, actor=context["actor"])

    def forbidden(_request):
        raise AssertionError("connector was called")

    monkeypatch.setattr("integrations.platforms.mock.MockPlatformConnector.publish", forbidden)
    assert execute_publish_task(task.id) is None
    task.refresh_from_db()
    assert task.status == PublishTask.Status.CANCELED
    assert not PublishAttempt.objects.filter(task=task).exists()


def test_cancel_after_provider_call_started_is_rejected(publishing_context, monkeypatch):
    context = publishing_context
    task = _task(context, "cancel-during")

    class CancelingConnector:
        def publish(self, request):
            with pytest.raises(PublishingConflict, match="reconciliation"):
                cancel_publish_task(task, actor=context["actor"])
            return PublishResult(succeeded=True, external_id=f"late-{request.task_id}")

    monkeypatch.setattr(
        "apps.publishing.services.get_connector",
        lambda _code, _account: CancelingConnector(),
    )

    post = execute_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUCCEEDED
    assert post is not None
    assert PublishAttempt.objects.get(task=task).status == PublishAttempt.Status.SUCCEEDED


def test_only_due_scheduled_tasks_are_queued(
    publishing_context, monkeypatch, django_capture_on_commit_callbacks,
):
    context = publishing_context
    due = _task(context, "due", scheduled=True)
    future_account = SocialAccount.objects.create(
        organization=context["organization"],
        platform=context["platform"],
        credential=context["account"].credential,
        external_id="mock-future",
        display_name="Future schedule account",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    future = _task(context, "future", scheduled=True, account=future_account)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=due.pk).update(
            scheduled_at=timezone.now() - timedelta(seconds=1)
        )
    dispatched = []
    monkeypatch.setattr(
        "apps.publishing.tasks.run_publish_task.delay", dispatched.append
    )

    with django_capture_on_commit_callbacks(execute=True):
        assert enqueue_due_publish_tasks(limit=10) == 1

    due.refresh_from_db()
    future.refresh_from_db()
    assert due.status == PublishTask.Status.QUEUED
    assert future.status == PublishTask.Status.SCHEDULED
    assert dispatched == [str(due.id)]


def test_attempt_and_post_history_reject_direct_mutation(publishing_context):
    task = _task(publishing_context, "history")
    post = execute_publish_task(task.id)
    attempt = post.attempt
    attempt.outcome = "forged"
    post.external_id = "forged"

    with pytest.raises(ValidationError):
        attempt.save()
    with pytest.raises(ValidationError):
        PublishedPost._base_manager.filter(pk=post.pk).update(external_id="forged")
    with pytest.raises(ValidationError):
        post.delete()


def test_one_platform_failure_does_not_poison_another_account(publishing_context):
    context = publishing_context
    failing_account = SocialAccount.objects.create(
        organization=context["organization"], platform=context["platform"],
        credential=context["account"].credential, external_id="mock-failing",
        display_name="Failing", publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"mock_outcome": "provider_error"},
    )
    failed = create_publish_task(
        content=context["content"], account=failing_account,
        idempotency_key="isolated-failure", actor=context["actor"],
    )
    succeeded = _task(context, "isolated-success")

    assert execute_publish_task(failed.id) is None
    post = execute_publish_task(succeeded.id)

    failed.refresh_from_db()
    succeeded.refresh_from_db()
    assert failed.status == PublishTask.Status.FAILED
    assert succeeded.status == PublishTask.Status.SUCCEEDED
    assert post.task_id == succeeded.id
    assert not PublishedPost.objects.filter(task=failed).exists()


def test_stale_claim_token_cannot_finalize_publish(publishing_context):
    task = _task(publishing_context, "stale-token")
    claimed_task, attempt = claim_publish_task(task.id)
    replacement_token = uuid.uuid4()
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(claim_token=replacement_token)

    result = complete_publish_success(
        task.id, claimed_task.claim_token,
        PublishResult(succeeded=True, external_id="must-not-persist"),
        actor=publishing_context["actor"],
    )

    task.refresh_from_db()
    attempt.refresh_from_db()
    assert result is None
    assert task.status == PublishTask.Status.RUNNING
    assert task.claim_token == replacement_token
    assert attempt.status == PublishAttempt.Status.STALE
    assert not PublishedPost.objects.filter(task=task).exists()


@pytest.mark.parametrize(
    "revoked_fact",
    [
        "task_fingerprint", "content_status", "content_head", "account_status",
        "credential", "capability",
    ],
)
def test_execution_revalidates_eligibility_before_connector(
    publishing_context, monkeypatch, revoked_fact,
):
    context = publishing_context
    task = _task(context, f"revalidate-{revoked_fact}")
    if revoked_fact == "task_fingerprint":
        with publishing_writes():
            PublishTask.objects.filter(pk=task.pk).update(request_fingerprint="0" * 64)
    elif revoked_fact == "content_status":
        with content_writes():
            PlatformContent.objects.filter(pk=context["content"].pk).update(
                status=PlatformContent.Status.IN_REVIEW
            )
    elif revoked_fact == "content_head":
        create_platform_revision(
            context["content"], actor=context["actor"],
            payload={**context["content"].payload, "title": "new head"},
        )
    elif revoked_fact == "account_status":
        context["account"].status = SocialAccount.Status.INACTIVE
        context["account"].save(update_fields=["status", "updated_at"])
    elif revoked_fact == "credential":
        credential = context["account"].credential
        credential.expires_at = timezone.now() - timedelta(seconds=1)
        credential.save(update_fields=["expires_at", "updated_at"])
    else:
        PlatformCapability.objects.filter(
            platform=context["platform"], code="PUBLISH"
        ).delete()

    calls = []

    class RecordingConnector:
        def publish(self, request):
            calls.append(request.task_id)
            return PublishResult(succeeded=True, external_id="must-not-publish")

    monkeypatch.setattr(
        "apps.publishing.services.get_connector",
        lambda _code, _account: RecordingConnector(),
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    assert calls == []
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error == {
        "code": "PUBLISH_NOT_ELIGIBLE",
        "message": "Publish eligibility changed before execution.",
    }
    assert attempt.status == PublishAttempt.Status.FAILED
    assert attempt.error == task.last_error
    assert not PublishedPost.objects.filter(task=task).exists()


def test_explicit_retry_stops_at_bounded_attempt_history(publishing_context):
    context = publishing_context
    context["account"].connector_metadata = {"mock_outcome": "provider_error"}
    context["account"].save(update_fields=["connector_metadata", "updated_at"])
    task = _task(context, "attempt-bound")

    for number in range(1, 11):
        assert execute_publish_task(task.id) is None
        task.refresh_from_db()
        assert task.attempt_number == number
        if number < 10:
            retry_publish_task(task, actor=context["actor"])

    with pytest.raises(PublishingConflict, match="attempt limit"):
        retry_publish_task(task, actor=context["actor"])
    assert PublishAttempt.objects.filter(task=task).count() == 10
