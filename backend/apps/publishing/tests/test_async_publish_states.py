from datetime import timedelta

import pytest
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.publishing.models import (
    PublishedPost,
    PublishTask,
    publishing_writes,
)
from apps.publishing.services import (
    PUBLISH_LEASE_SECONDS,
    PublishingConflict,
    claim_publish_task,
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
    assert reap_stale_publish_tasks(now=expired) == 1

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
    assert reap_stale_publish_tasks(now=expired) == 1

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

    sync_publish_item_from_task(task_id=task.id)

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
    assert reap_stale_publish_tasks(now=expired) == 1
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
