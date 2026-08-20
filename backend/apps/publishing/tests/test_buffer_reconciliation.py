from types import SimpleNamespace
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.identity.models import Organization
from apps.publishing.models import (
    PublishAttempt,
    PublishedPost,
    PublishReconciliationAttempt,
    PublishTask,
)
from apps.publishing.reconciliation import reconcile_buffer_publish_task
from apps.publishing.reconciliation import (
    finalize_buffer_reconciliation,
    finalize_unknown_buffer_reconciliation,
    load_reconciliation_snapshot,
    load_unknown_reconciliation_snapshot,
    reconcile_unknown_buffer_publish_task,
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
    BufferAssetIdentity,
    BufferPostObservation,
    BufferCandidateSearchResult,
    BufferPostCandidate,
    BufferPostQueryResult,
)
from integrations.platforms.buffer_connector import provider_candidate_fingerprint

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


class CandidateConnector:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def search_post_candidates(self, request):
        self.requests.append(request)
        return self.result

    def publish(self, request):
        raise AssertionError("unknown reconciliation must never call createPost")


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


def _unknown(context, monkeypatch):
    account, connection = _buffer_account(context, monkeypatch)
    submitter = RecordingConnector(
        OfficialPublishResult(status="FAILED", error_code="OUTCOME_UNKNOWN")
    )
    _runtime(monkeypatch, submitter)
    task = create_publish_task(
        content=context["content"], account=account,
        idempotency_key="buffer-unknown-reconcile", actor=context["actor"],
    )
    execute_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert len(task.provider_request_fingerprint) == 64
    return task, account, connection


def _query_runtime(monkeypatch, connector):
    from apps.publishing import reconciliation

    registry = SimpleNamespace(resolve=lambda account: connector)
    monkeypatch.setattr(
        reconciliation, "get_social_provider_runtime",
        lambda: SimpleNamespace(connector_registry=registry),
    )


def _end_query_window(task):
    call_started_at = timezone.now() - timedelta(minutes=16)
    from apps.publishing.models import publishing_writes

    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(
            provider_call_started_at=call_started_at,
            next_reconcile_at=None,
        )
        PublishAttempt.objects.filter(task=task).update(
            provider_call_started_at=call_started_at,
        )
    task.refresh_from_db()
    return call_started_at + timedelta(minutes=15)


def _candidate(task, *, post_id="candidate-1", text="Body", channel_id="buffer-channel-1", service="mock", created_at=None, status="sent", assets=()):
    created_at = created_at or task.provider_call_started_at
    return BufferPostCandidate(
        post_id=post_id,
        channel_id=channel_id,
        channel_service=service,
        status=status,
        text=text,
        created_at=created_at,
        due_at=None,
        sent_at=created_at if status == "sent" else None,
        scheduling_type="automatic",
        share_mode="shareNow",
        assets=assets,
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


def test_post_not_found_before_query_window_end_is_only_deferred(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    window_end = task.provider_call_started_at + timedelta(minutes=15)
    connector = QueryConnector(
        BufferPostQueryResult(ok=False, error_code="BUFFER_POST_NOT_FOUND")
    )
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert task.next_reconcile_at == window_end
    assert task.reconciliation_attempts.get().result == PublishReconciliationAttempt.Result.DEFERRED
    assert not PublishedPost.objects.filter(task=task).exists()


def test_post_not_found_after_query_window_end_needs_attention(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    _end_query_window(task)
    connector = QueryConnector(
        BufferPostQueryResult(ok=False, error_code="BUFFER_POST_NOT_FOUND")
    )
    _query_runtime(monkeypatch, connector)

    reconcile_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_POST_NOT_FOUND"
    assert not PublishedPost.objects.filter(task=task).exists()


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


def test_worker_selection_waits_for_initial_submitted_delay(publishing_context, monkeypatch):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    assert select_due_buffer_reconciliation_ids() == []
    assert select_due_buffer_reconciliation_ids(now=task.next_reconcile_at) == [task.id]
    assert select_due_buffer_reconciliation_ids() == []


def test_worker_selection_includes_due_unknown_without_retrying_publish(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    assert select_due_buffer_reconciliation_ids() == []
    assert select_due_buffer_reconciliation_ids(now=task.next_reconcile_at) == [task.id]
    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN


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


def test_unknown_unique_sent_candidate_binds_id_and_reuses_exact_reconciliation(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    connector = CandidateConnector(
        BufferCandidateSearchResult(ok=True, candidates=(_candidate(task),))
    )
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(
        task.id, organization=publishing_context["organization"],
        actor=publishing_context["actor"],
    )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUCCEEDED
    assert task.provider_submission_id == "candidate-1"
    assert PublishAttempt.objects.get(task=task).provider_submission_id == "candidate-1"
    assert PublishedPost.objects.get(task=task).external_id == "candidate-1"
    audits = list(task.reconciliation_attempts.order_by("sequence_number"))
    assert [audit.mode for audit in audits] == ["UNKNOWN_MATCH", "EXACT_ID"]
    assert audits[0].candidate_count == 1
    assert audits[0].matched_provider_post_id == "candidate-1"
    assert len(connector.requests) == 1
    request = connector.requests[0]
    assert request.window_start == task.provider_call_started_at - timedelta(minutes=2)
    assert request.window_end == task.provider_call_started_at + timedelta(minutes=15)


def test_unknown_unique_scheduled_candidate_binds_id_and_remains_submitted(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    connector = CandidateConnector(BufferCandidateSearchResult(
        ok=True, candidates=(_candidate(task, status="scheduled"),)
    ))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert task.provider_submission_id == "candidate-1"
    assert not PublishedPost.objects.filter(task=task).exists()
    assert [
        audit.result for audit in task.reconciliation_attempts.order_by("sequence_number")
    ] == [PublishReconciliationAttempt.Result.MATCHED, PublishReconciliationAttempt.Result.DEFERRED]


def test_unknown_zero_candidates_before_window_end_are_only_deferred(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    window_end = task.provider_call_started_at + timedelta(minutes=15)
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True, candidates=()))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    audit = task.reconciliation_attempts.get()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.next_reconcile_at == window_end
    assert audit.result == PublishReconciliationAttempt.Result.DEFERRED
    assert audit.safe_error_code == "BUFFER_RECONCILIATION_NO_MATCH"
    assert audit.candidate_count == 0
    assert not PublishedPost.objects.filter(task=task).exists()


def test_unknown_zero_candidates_after_window_end_need_attention(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    _end_query_window(task)
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True, candidates=()))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    audit = task.reconciliation_attempts.get()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_NO_MATCH"
    assert audit.candidate_count == 0
    assert audit.matched_provider_post_id == ""
    assert not PublishedPost.objects.filter(task=task).exists()
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)


def test_unknown_multiple_exact_candidates_need_attention(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    connector = CandidateConnector(BufferCandidateSearchResult(
        ok=True,
        candidates=tuple(
            _candidate(task, post_id=f"candidate-{value}")
            for value in ("one", "two")
        ),
    ))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    audit = task.reconciliation_attempts.get()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_AMBIGUOUS"
    assert audit.candidate_count == 2
    assert not PublishedPost.objects.filter(task=task).exists()


def test_unknown_truncated_scan_cannot_claim_unique_match(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    connector = CandidateConnector(BufferCandidateSearchResult(
        ok=True, candidates=(_candidate(task),), truncated=True
    ))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_AMBIGUOUS"
    assert task.provider_submission_id == ""


def test_unknown_missing_persisted_fingerprint_needs_attention_without_query(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(provider_request_fingerprint="")
        PublishAttempt.objects.filter(task=task).update(provider_request_fingerprint="")
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_EVIDENCE_MISSING"
    assert connector.requests == []


def test_unknown_expired_window_needs_attention_without_query(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    expired_at = timezone.now() - timedelta(days=8)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(provider_call_started_at=expired_at)
        PublishAttempt.objects.filter(task=task).update(provider_call_started_at=expired_at)
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_EXPIRED"
    assert connector.requests == []


def test_unknown_reconciliation_is_organization_scoped(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    other = Organization.objects.create(name="Other D2 Org", slug="other-d2-org")
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True))
    _query_runtime(monkeypatch, connector)

    with pytest.raises(PublishingConflict):
        reconcile_unknown_buffer_publish_task(task.id, organization=other)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert connector.requests == []


@pytest.mark.parametrize(
    "candidate_changes",
    [
        {"text": "different body"},
        {"channel_id": "different-channel"},
        {"service": "linkedin"},
        {"created_at": timezone.now() - timedelta(hours=1)},
        {"assets": (BufferAssetIdentity("image", "image/jpeg", "https://cdn.example/other.jpg"),)},
    ],
)
def test_unknown_nearby_but_not_exact_candidate_is_not_matched(
    publishing_context, monkeypatch, candidate_changes,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    _end_query_window(task)
    connector = CandidateConnector(BufferCandidateSearchResult(
        ok=True, candidates=(_candidate(task, **candidate_changes),)
    ))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_NO_MATCH"
    assert task.provider_submission_id == ""
    assert not PublishedPost.objects.filter(task=task).exists()


def test_unknown_missing_history_never_rebuilds_from_current_content(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(provider_request_fingerprint="")
        PublishAttempt.objects.filter(task=task).update(provider_request_fingerprint="")
    from apps.content.models import content_writes
    with content_writes():
        publishing_context["content"].payload = {"title": "edited after submit", "body": "new"}
        publishing_context["content"].save(update_fields=["payload", "updated_at"])
    connector = CandidateConnector(BufferCandidateSearchResult(
        ok=True, candidates=(_candidate(task),)
    ))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_EVIDENCE_MISSING"
    assert connector.requests == []


def test_unknown_stale_credential_snapshot_does_not_bind_candidate(
    publishing_context, monkeypatch,
):
    task, _account, connection = _unknown(publishing_context, monkeypatch)
    snapshot = load_unknown_reconciliation_snapshot(task.id)
    connection.display_name = "Rotated after query began"
    connection.save(update_fields=["display_name", "updated_at"])

    finalize_unknown_buffer_reconciliation(
        snapshot,
        BufferCandidateSearchResult(ok=True, candidates=(_candidate(task),)),
    )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.provider_submission_id == ""
    assert task.reconciliation_attempts.get().result == PublishReconciliationAttempt.Result.STALE


def test_unknown_same_snapshot_can_only_bind_once(publishing_context, monkeypatch):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    snapshot = load_unknown_reconciliation_snapshot(task.id)
    result = BufferCandidateSearchResult(ok=True, candidates=(_candidate(task),))

    finalize_unknown_buffer_reconciliation(snapshot, result, actor=publishing_context["actor"])
    finalize_unknown_buffer_reconciliation(snapshot, result, actor=publishing_context["actor"])

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUCCEEDED
    assert PublishedPost.objects.filter(task=task).count() == 1
    assert task.reconciliation_attempts.filter(mode="UNKNOWN_MATCH", result="MATCHED").count() == 1


def test_unknown_audit_contains_only_safe_candidate_evidence(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    asset_url = "https://cdn.example.test/sensitive-asset-name.jpg"
    candidate = _candidate(task, assets=(BufferAssetIdentity("image", "image/jpeg", asset_url),))
    fingerprint = provider_candidate_fingerprint(candidate)
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(provider_request_fingerprint=fingerprint)
        PublishAttempt.objects.filter(task=task).update(provider_request_fingerprint=fingerprint)
    task.refresh_from_db()
    connector = CandidateConnector(BufferCandidateSearchResult(ok=True, candidates=(candidate,)))
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id, actor=publishing_context["actor"])

    audit = task.reconciliation_attempts.get(mode="UNKNOWN_MATCH")
    assert audit.candidate_count == 1
    assert len(audit.candidate_set_fingerprint) == 64
    serialized = str({field.name: getattr(audit, field.name) for field in audit._meta.fields})
    assert asset_url not in serialized
    assert "Body" not in serialized
    assert "vault://" not in serialized


@pytest.mark.parametrize(
    "error_code", ["BUFFER_RATE_LIMITED", "BUFFER_PROVIDER_UNAVAILABLE", "BUFFER_AUTHENTICATION_REQUIRED"],
)
def test_unknown_query_failure_stays_unknown_and_never_becomes_no_match(
    publishing_context, monkeypatch, error_code,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    connector = CandidateConnector(
        BufferCandidateSearchResult(ok=False, error_code=error_code, retry_after_seconds=80)
    )
    _query_runtime(monkeypatch, connector)

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.reconciliation_error_code == error_code
    assert task.next_reconcile_at is not None
    from apps.publishing.models import publishing_writes
    with publishing_writes():
        PublishTask.objects.filter(pk=task.pk).update(status=PublishTask.Status.SUBMISSION_UNKNOWN)
    assert select_due_buffer_reconciliation_ids() == []


def test_unknown_provider_exception_is_sanitized_and_deferred(
    publishing_context, monkeypatch, caplog,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)
    marker = "Bearer buffer-secret raw GraphQL response"

    class ExplodingCandidateConnector:
        def search_post_candidates(self, request):
            raise RuntimeError(marker)

        def publish(self, request):
            raise AssertionError("unknown reconciliation must never call createPost")

    _query_runtime(monkeypatch, ExplodingCandidateConnector())

    reconcile_unknown_buffer_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.reconciliation_error_code == "BUFFER_PROVIDER_UNAVAILABLE"
    assert marker not in caplog.text
    assert marker not in str(task.last_error)
