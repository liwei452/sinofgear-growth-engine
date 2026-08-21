from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.publishing.models import (
    PublishedPost,
    PublishAttempt,
    PublishTask,
    publishing_writes,
)
from apps.publishing.services import (
    PUBLISH_LEASE_SECONDS,
    PublishingConflict,
    cancel_publish_task,
    claim_publish_task,
    complete_publish_failure,
    complete_publish_submitted,
    create_publish_task,
    execute_publish_task,
    publish_task_consistency_queryset,
    publish_task_is_consistent,
    reap_stale_publish_tasks,
    retry_publish_task,
)
from integrations.platforms.base import OfficialPublishResult, PublishResult


def _patch_connector(monkeypatch, publish_result):
    from apps.publishing import services

    class FakeConnector:
        def __init__(self, result):
            self.result = result
            self.calls = []

        def publish(self, request):
            self.calls.append(request)
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    connector = FakeConnector(publish_result)
    monkeypatch.setattr(services, "get_connector", lambda code, account: connector)
    return connector


def test_provider_final_success_creates_post_and_publishes_content(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-a",
        actor=context["actor"],
    )

    post = execute_publish_task(task.id)

    assert post is not None
    task.refresh_from_db()
    context["content"].refresh_from_db()
    assert task.status == PublishTask.Status.SUCCEEDED
    assert context["content"].status == PlatformContent.Status.PUBLISHED
    assert PublishedPost.objects.filter(task=task).exists()


def test_finalization_exception_after_provider_success_is_unknown(
    publishing_context, monkeypatch,
):
    from apps.publishing import services

    context = publishing_context
    _patch_connector(
        monkeypatch,
        PublishResult(succeeded=True, external_id="provider-created-post"),
    )
    monkeypatch.setattr(
        services,
        "complete_publish_success",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db finalize failed")),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-finalize-unknown",
        actor=context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    assert task.provider_call_started_at is not None
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"
    with pytest.raises(PublishingConflict, match="reconciliation, not retry"):
        retry_publish_task(task)


@pytest.mark.parametrize(
    ("result", "finalizer_name"),
    [
        (
            OfficialPublishResult(status="SUBMITTED", submission_id="buffer-finalizer"),
            "complete_publish_submitted",
        ),
        (
            PublishResult(succeeded=False, error_code="PROVIDER_ERROR"),
            "complete_publish_failure",
        ),
    ],
)
def test_finalizer_exception_after_provider_call_is_unknown(
    publishing_context, monkeypatch, result, finalizer_name,
):
    from apps.publishing import services

    context = publishing_context
    _patch_connector(monkeypatch, result)
    monkeypatch.setattr(
        services,
        finalizer_name,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database finalizer failed")
        ),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key=f"async-{finalizer_name}-unknown",
        actor=context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"


def test_malformed_result_classification_after_provider_call_is_unknown(
    publishing_context, monkeypatch,
):
    class MalformedResult:
        succeeded = False
        submitted = False

        @property
        def error_code(self):
            raise RuntimeError("malformed result property")

    context = publishing_context
    _patch_connector(monkeypatch, MalformedResult())
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-malformed-result-unknown",
        actor=context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"


def test_unknown_finalizer_exception_does_not_escape_or_allow_cancel(
    publishing_context, monkeypatch,
):
    from apps.publishing import services

    context = publishing_context
    _patch_connector(
        monkeypatch,
        PublishResult(succeeded=False, error_code="OUTCOME_UNKNOWN"),
    )
    monkeypatch.setattr(
        services,
        "complete_publish_unknown",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("unknown finalizer unavailable")
        ),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-unknown-finalizer-guarded",
        actor=context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    assert task.status == PublishTask.Status.RUNNING
    assert task.provider_call_started_at is not None
    with pytest.raises(PublishingConflict, match="reconciliation"):
        cancel_publish_task(task, actor=context["actor"])


def test_safe_error_defaults_for_result_without_error_code():
    from apps.publishing.services import SAFE_PUBLISH_ERRORS, _safe_error

    assert _safe_error(object()) == SAFE_PUBLISH_ERRORS["PROVIDER_ERROR"]


class _ExplodingErrorCode:
    @property
    def error_code(self):
        raise RuntimeError("provider error detail must not escape")


class _ExplodingString(str):
    def __hash__(self):
        raise RuntimeError("provider string hash must not escape")


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(_ExplodingErrorCode(), id="property-raises"),
        pytest.param(
            SimpleNamespace(error_code=_ExplodingString("RATE_LIMITED")),
            id="str-subclass",
        ),
        pytest.param(SimpleNamespace(error_code=[]), id="list"),
        pytest.param(SimpleNamespace(error_code={}), id="dict"),
        pytest.param(SimpleNamespace(error_code=123), id="integer"),
    ],
)
def test_safe_error_defaults_for_malformed_error_code(result):
    from apps.publishing.services import SAFE_PUBLISH_ERRORS, _safe_error

    assert _safe_error(result) == SAFE_PUBLISH_ERRORS["PROVIDER_ERROR"]


def test_safe_error_preserves_exact_rate_limited_mapping():
    from apps.publishing.services import SAFE_PUBLISH_ERRORS, _safe_error

    result = SimpleNamespace(error_code="RATE_LIMITED", retry_after_seconds=42)

    assert _safe_error(result) == SAFE_PUBLISH_ERRORS["RATE_LIMITED"]


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(_ExplodingErrorCode(), id="property-raises"),
        pytest.param(
            SimpleNamespace(error_code=_ExplodingString("RATE_LIMITED")),
            id="str-subclass",
        ),
    ],
)
def test_complete_publish_failure_safely_handles_malformed_error_code(
    publishing_context, result,
):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-malformed-failure-finalizer",
        actor=context["actor"],
    )
    running_task, attempt = claim_publish_task(task.id)

    completed = complete_publish_failure(
        running_task.id,
        attempt.claim_token,
        result,
    )

    completed.refresh_from_db()
    attempt = PublishAttempt.objects.get(pk=attempt.pk)
    assert completed.status == PublishTask.Status.FAILED
    assert completed.last_error == {
        "code": "PROVIDER_ERROR",
        "message": "Provider rejected the publish request.",
    }
    assert completed.retry_not_before is None
    assert attempt.status == PublishAttempt.Status.FAILED
    assert attempt.outcome == "PROVIDER_ERROR"
    assert attempt.error == completed.last_error


_SENSITIVE_PROVIDER_MARKER = "SENSITIVE_PROVIDER_DETAIL_C2_2"


class _ExplodingProviderResult:
    def __init__(self, exploding_field):
        self.exploding_field = exploding_field

    def _value(self, field, value):
        if self.exploding_field == field:
            raise RuntimeError(f"{_SENSITIVE_PROVIDER_MARKER}:{field}")
        return value

    @property
    def succeeded(self):
        return self._value(
            "succeeded",
            self.exploding_field == "external_id",
        )

    @property
    def submitted(self):
        return self._value(
            "submitted",
            self.exploding_field == "submission_id",
        )

    @property
    def submission_id(self):
        return self._value("submission_id", "buffer-sensitive-submission")

    @property
    def external_id(self):
        return self._value("external_id", "buffer-sensitive-post")

    @property
    def error_code(self):
        code = "RATE_LIMITED" if self.exploding_field == "retry_after_seconds" else ""
        return self._value("error_code", code)

    @property
    def retry_after_seconds(self):
        return self._value("retry_after_seconds", 42)


@pytest.mark.parametrize(
    "exploding_field",
    [
        "succeeded",
        "submitted",
        "submission_id",
        "external_id",
        "error_code",
        "retry_after_seconds",
    ],
)
def test_malformed_provider_result_is_unknown_without_sensitive_logging(
    publishing_context, monkeypatch, caplog, exploding_field,
):
    context = publishing_context
    _patch_connector(monkeypatch, _ExplodingProviderResult(exploding_field))
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key=f"async-sensitive-result-{exploding_field}",
        actor=context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"
    assert not PublishedPost.objects.filter(task=task).exists()
    with pytest.raises(PublishingConflict, match="reconciliation, not retry"):
        retry_publish_task(task)
    assert _SENSITIVE_PROVIDER_MARKER not in caplog.text


def test_provider_acceptance_stays_submitted(publishing_context, monkeypatch):
    context = publishing_context
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-sub-1"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-b",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    assert result is None
    task.refresh_from_db()
    context["content"].refresh_from_db()
    assert task.status == PublishTask.Status.SUBMITTED
    assert task.provider_submission_id == "buffer-sub-1"
    assert not PublishedPost.objects.filter(task=task).exists()
    assert context["content"].status == PlatformContent.Status.APPROVED
    assert publish_task_is_consistent(task)


def test_provider_outcome_unknown_stays_unknown(publishing_context, monkeypatch):
    context = publishing_context
    _patch_connector(
        monkeypatch,
        PublishResult(succeeded=False, error_code="OUTCOME_UNKNOWN"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-c",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    assert result is None
    task.refresh_from_db()
    context["content"].refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"
    assert not PublishedPost.objects.filter(task=task).exists()
    assert context["content"].status == PlatformContent.Status.APPROVED
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)


def test_duplicate_execution_does_not_call_connector_again(
    publishing_context, monkeypatch
):
    context = publishing_context
    connector = _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-sub-1"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-d",
        actor=context["actor"],
    )

    execute_publish_task(task.id)
    execute_publish_task(task.id)

    assert len(connector.calls) == 1


def test_stale_worker_before_provider_call_is_retryable(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-e",
        actor=context["actor"],
    )
    claimed = claim_publish_task(task.id)
    assert claimed is not None

    expired = timezone.now() + timedelta(seconds=PUBLISH_LEASE_SECONDS + 1)
    assert reap_stale_publish_tasks(
        organization_id=task.organization_id,
        now=expired,
    ) == 1

    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "STALE_WORKER"
    retry_publish_task(task)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.QUEUED


def test_stale_worker_after_provider_call_is_unknown(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-e2",
        actor=context["actor"],
    )
    claimed = claim_publish_task(task.id)
    assert claimed is not None
    claimed_task, attempt = claimed
    from apps.publishing.services import _mark_provider_call_started

    _mark_provider_call_started(claimed_task, attempt)

    expired = timezone.now() + timedelta(seconds=PUBLISH_LEASE_SECONDS + 1)
    assert reap_stale_publish_tasks(
        organization_id=task.organization_id,
        now=expired,
    ) == 1

    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)


def test_malformed_submitted_attempt_history_is_rejected(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-f",
        actor=context["actor"],
    )
    claimed = claim_publish_task(task.id)
    assert claimed is not None
    claimed_task, attempt = claimed
    complete_publish_submitted(
        claimed_task.id,
        attempt.claim_token,
        OfficialPublishResult(status="SUBMITTED", submission_id="sub-1"),
    )
    with publishing_writes():
        attempt.provider_submission_id = ""
        attempt.save(update_fields=["provider_submission_id", "updated_at"])

    loaded = publish_task_consistency_queryset(context["organization"]).get(
        pk=claimed_task.pk
    )
    assert not publish_task_is_consistent(loaded)


def test_growth_item_stays_waiting_for_submitted_task(
    publishing_context, monkeypatch
):
    from apps.growth.models import (
        ChannelPackage,
        GrowthPublishBatch,
        GrowthPublishItem,
    )
    from apps.growth.publishing import sync_publish_item_from_task
    context = publishing_context
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-sub-1"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-g",
        actor=context["actor"],
    )
    execute_publish_task(task.id)

    package = ChannelPackage.objects.create(
        organization=context["organization"],
        channel="MOCK",
        payload={"title": "Inspection proof"},
        status="APPROVED",
        is_demo=True,
    )
    batch = GrowthPublishBatch.objects.create(
        organization=context["organization"],
        created_by=context["actor"],
        idempotency_key="async-g-batch",
        request_fingerprint="g" * 64,
        status=GrowthPublishBatch.Status.QUEUED,
        is_demo=True,
    )
    item = GrowthPublishItem.objects.create(
        organization=context["organization"],
        batch=batch,
        channel_package=package,
        publish_task=task,
        social_account=context["account"],
        channel="MOCK",
        payload_snapshot={"title": "Inspection proof"},
        status=GrowthPublishItem.Status.DELEGATED,
    )

    sync_publish_item_from_task(
        task_id=task.id,
        organization_id=task.organization_id,
    )

    item.refresh_from_db()
    assert item.status == GrowthPublishItem.Status.DELEGATED
    assert item.external_post_id == ""


def test_submitted_without_submission_id_becomes_unknown(
    publishing_context, monkeypatch
):
    context = publishing_context
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id=""),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-empty-sub",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    assert result is None
    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert publish_task_is_consistent(task)
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)


def test_submitted_counts_toward_daily_limit(publishing_context, monkeypatch):
    context = publishing_context
    context["organization"].daily_publish_limit = 1
    context["organization"].save(update_fields=["daily_publish_limit"])
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id="sub-1"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="limit-sub-1",
        actor=context["actor"],
    )
    execute_publish_task(task.id)

    with pytest.raises(PublishingConflict, match="Daily publishing limit"):
        create_publish_task(
            content=context["content"],
            account=context["account"],
            idempotency_key="limit-sub-2",
            actor=context["actor"],
        )


def test_serializers_expose_provider_submission_id(
    publishing_context, monkeypatch
):
    from apps.publishing.serializers import PublishTaskSerializer

    context = publishing_context
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-sub-1"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-serializer",
        actor=context["actor"],
    )
    execute_publish_task(task.id)
    task.refresh_from_db()

    data = PublishTaskSerializer(task).data

    assert data["provider_submission_id"] == "buffer-sub-1"
    assert data["provider_call_started_at"] is not None
    assert data["attempts"][-1]["provider_submission_id"] == "buffer-sub-1"
    assert data["attempts"][-1]["provider_call_started_at"] is not None


def test_complete_submitted_rejects_empty_submission_id(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-empty-direct",
        actor=context["actor"],
    )
    claimed = claim_publish_task(task.id)
    assert claimed is not None
    claimed_task, attempt = claimed

    with pytest.raises(PublishingConflict, match="submission id"):
        complete_publish_submitted(
            claimed_task.id,
            attempt.claim_token,
            OfficialPublishResult(status="SUBMITTED", submission_id=""),
        )

    claimed_task.refresh_from_db()
    assert claimed_task.status == PublishTask.Status.RUNNING


def test_retry_clears_provider_call_started_at(publishing_context, monkeypatch):
    context = publishing_context
    _patch_connector(
        monkeypatch,
        PublishResult(succeeded=False, error_code="PROVIDER_ERROR"),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-retry-call",
        actor=context["actor"],
    )
    execute_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.provider_call_started_at is not None

    retry_publish_task(task)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.QUEUED
    assert task.provider_call_started_at is None

    claimed = claim_publish_task(task.id)
    assert claimed is not None
    expired = timezone.now() + timedelta(seconds=PUBLISH_LEASE_SECONDS + 1)
    assert reap_stale_publish_tasks(
        organization_id=task.organization_id,
        now=expired,
    ) == 1
    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "STALE_WORKER"


def test_tampered_provider_call_started_at_is_rejected(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-tamper-call",
        actor=context["actor"],
    )
    claimed = claim_publish_task(task.id)
    assert claimed is not None
    claimed_task, attempt = claimed
    from apps.publishing.services import _mark_provider_call_started

    _mark_provider_call_started(claimed_task, attempt)
    complete_publish_submitted(
        claimed_task.id,
        attempt.claim_token,
        OfficialPublishResult(status="SUBMITTED", submission_id="sub-1"),
    )

    with publishing_writes():
        claimed_task.provider_call_started_at = None
        claimed_task.save(update_fields=["provider_call_started_at", "updated_at"])
    loaded = publish_task_consistency_queryset(context["organization"]).get(
        pk=claimed_task.pk
    )
    assert not publish_task_is_consistent(loaded)


@pytest.mark.parametrize("submission_id", ["", "   ", 123, "x" * 256])
def test_invalid_submission_id_routes_to_unknown(
    publishing_context, monkeypatch, submission_id
):
    context = publishing_context
    _patch_connector(
        monkeypatch,
        OfficialPublishResult(status="SUBMITTED", submission_id=submission_id),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="async-bad-sub",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    assert result is None
    task.refresh_from_db()
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert not PublishedPost.objects.filter(task=task).exists()
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)
