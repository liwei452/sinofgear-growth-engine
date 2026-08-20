from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.publishing.models import (
    PublishAttempt,
    PublishedPost,
    PublishReconciliationAttempt,
    PublishTask,
)
from apps.publishing.reconciliation import reconcile_buffer_publish_task
from apps.publishing.reconciliation import (
    finalize_buffer_reconciliation,
    load_reconciliation_snapshot,
    select_due_buffer_reconciliation_ids,
)
from apps.publishing.services import (
    PublishingConflict,
    create_publish_task,
    execute_publish_task,
    retry_publish_task,
)
from integrations.platforms.base import OfficialPublishResult
from integrations.platforms.buffer_types import (
    BufferPostObservation,
    BufferPostQueryResult,
)

from .test_buffer_publish_submission import RecordingConnector, _buffer_account, _runtime


class QueryConnector:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def fetch_post(self, request):
        self.requests.append(request)
        return self.result

    def publish(self, request):
        raise AssertionError("reconciliation must never call createPost")


def _submitted(context, monkeypatch):
    account, connection = _buffer_account(context, monkeypatch)
    submitter = RecordingConnector(
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-post-1")
    )
    _runtime(monkeypatch, submitter)
    task = create_publish_task(
        content=context["content"], account=account,
        idempotency_key="buffer-reconcile", actor=context["actor"],
    )
    execute_publish_task(task.id)
    task.refresh_from_db()
    return task, account, connection


def _query_runtime(monkeypatch, connector):
    from apps.publishing import reconciliation

    registry = SimpleNamespace(resolve=lambda account: connector)
    monkeypatch.setattr(
        reconciliation, "get_social_provider_runtime",
        lambda: SimpleNamespace(connector_registry=registry),
    )


def _observation(*, status="sent", sent_at=None, post_id="buffer-post-1", channel_id="buffer-channel-1", service="mock"):
    return BufferPostObservation(
        post_id=post_id,
        channel_id=channel_id,
        channel_service=service,
        status=status,
        sent_at=sent_at if sent_at is not None else timezone.now(),
    )


@pytest.mark.parametrize("status", ["scheduled", "sending"])
def test_non_final_buffer_status_defers_without_post(publishing_context, monkeypatch, status):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(BufferPostQueryResult(ok=True, observation=_observation(status=status)))
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id, organization=publishing_context["organization"])

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert task.next_reconcile_at is not None
    assert not PublishedPost.objects.filter(task=task).exists()
    assert task.reconciliation_attempts.get().result == PublishReconciliationAttempt.Result.DEFERRED
    assert len(connector.requests) == 1


def test_sent_converges_using_provider_sent_at_and_is_idempotent(publishing_context, monkeypatch):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    sent_at = timezone.now().replace(microsecond=0)
    connector = QueryConnector(
        BufferPostQueryResult(ok=True, observation=_observation(sent_at=sent_at))
    )
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id, organization=publishing_context["organization"])

    task.refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    post = PublishedPost.objects.get(task=task)
    publishing_context["content"].refresh_from_db()
    assert task.status == PublishTask.Status.SUCCEEDED
    assert attempt.status == PublishAttempt.Status.SUCCEEDED
    assert post.published_at == sent_at
    assert post.external_id == "buffer-post-1"
    assert publishing_context["content"].status == PlatformContent.Status.PUBLISHED
    with pytest.raises(PublishingConflict):
        reconcile_buffer_publish_task(task.id, organization=publishing_context["organization"])
    assert PublishedPost.objects.filter(task=task).count() == 1


def test_provider_error_is_explicit_failure_without_post(publishing_context, monkeypatch):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(
        BufferPostQueryResult(ok=True, observation=_observation(status="error", sent_at=None))
    )
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "BUFFER_PUBLISH_FAILED"
    assert not PublishedPost.objects.filter(task=task).exists()


@pytest.mark.parametrize("status", ["draft", "needs_approval"])
def test_ambiguous_buffer_status_needs_attention_and_blocks_retry(
    publishing_context, monkeypatch, status,
):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(
        BufferPostQueryResult(ok=True, observation=_observation(status=status, sent_at=None))
    )
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert PublishAttempt.objects.get(task=task).status == PublishAttempt.Status.NEEDS_ATTENTION
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"post_id": "other"}, "BUFFER_POST_MISMATCH"),
        ({"channel_id": "other"}, "BUFFER_POST_MISMATCH"),
        ({"service": "linkedin"}, "BUFFER_POST_MISMATCH"),
    ],
)
def test_identity_mismatch_needs_attention(publishing_context, monkeypatch, changes, code):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(
        BufferPostQueryResult(ok=True, observation=_observation(**changes))
    )
    _query_runtime(monkeypatch, connector)
    reconcile_buffer_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.reconciliation_error_code == code


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("BUFFER_POST_NOT_FOUND", PublishTask.Status.NEEDS_ATTENTION),
        ("BUFFER_PROVIDER_UNAVAILABLE", PublishTask.Status.SUBMITTED),
        ("BUFFER_RATE_LIMITED", PublishTask.Status.SUBMITTED),
        ("BUFFER_AUTHENTICATION_REQUIRED", PublishTask.Status.SUBMITTED),
    ],
)
def test_safe_query_errors_never_become_publish_failure(
    publishing_context, monkeypatch, error_code, expected_status,
):
    task, account, connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(
        BufferPostQueryResult(ok=False, error_code=error_code, retry_after_seconds=90)
    )
    _query_runtime(monkeypatch, connector)
    reconcile_buffer_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == expected_status
    assert not PublishedPost.objects.filter(task=task).exists()
    if error_code == "BUFFER_RATE_LIMITED":
        assert 80 <= (task.next_reconcile_at - timezone.now()).total_seconds() <= 90
    if error_code == "BUFFER_AUTHENTICATION_REQUIRED":
        account.refresh_from_db()
        connection.refresh_from_db()
        assert account.connection_state == account.ConnectionState.REAUTHORIZATION_REQUIRED
        assert connection.connection_state == connection.ConnectionState.REAUTHORIZATION_REQUIRED


def test_reconciliation_audit_is_append_only(publishing_context, monkeypatch):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    connector = QueryConnector(
        BufferPostQueryResult(ok=True, observation=_observation(status="scheduled"))
    )
    _query_runtime(monkeypatch, connector)
    reconcile_buffer_publish_task(task.id)
    audit = PublishReconciliationAttempt.objects.get(publish_task=task)
    audit.safe_error_code = "token=secret"
    with pytest.raises(ValidationError):
        audit.save()
    with pytest.raises(ValidationError):
        PublishReconciliationAttempt.objects.filter(pk=audit.pk).update(result="FAILED")
    with pytest.raises(ValidationError):
        audit.delete()
    assert "metadata" not in {field.name for field in audit._meta.fields}


def test_stale_credential_snapshot_does_not_overwrite_task(publishing_context, monkeypatch):
    task, _account, connection = _submitted(publishing_context, monkeypatch)
    snapshot = load_reconciliation_snapshot(task.id)
    connection.display_name = "Rotated while querying"
    connection.save(update_fields=["display_name", "updated_at"])

    finalize_buffer_reconciliation(
        snapshot,
        BufferPostQueryResult(ok=True, observation=_observation()),
        actor=publishing_context["actor"],
    )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert not PublishedPost.objects.filter(task=task).exists()
    assert task.reconciliation_attempts.get().result == PublishReconciliationAttempt.Result.STALE


def test_worker_selection_excludes_unknown_outcome(publishing_context, monkeypatch):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    assert select_due_buffer_reconciliation_ids() == [task.id]
    assert select_due_buffer_reconciliation_ids() == []


def test_provider_exception_details_never_reach_logs_or_task(
    publishing_context, monkeypatch, caplog,
):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    marker = "Bearer secret-token raw GraphQL message"

    class ExplodingQueryConnector:
        def fetch_post(self, request):
            raise RuntimeError(marker)

    _query_runtime(monkeypatch, ExplodingQueryConnector())
    reconcile_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert task.reconciliation_error_code == "BUFFER_PROVIDER_UNAVAILABLE"
    assert marker not in caplog.text
    assert marker not in str(task.last_error)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(status=PublishTask.Status.SUBMISSION_UNKNOWN)
    assert select_due_buffer_reconciliation_ids() == []
