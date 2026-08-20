from types import SimpleNamespace

import pytest
from django.db import IntegrityError, transaction

from apps.content.models import PlatformContent
from apps.platforms.capabilities import CONNECTOR_CAPABILITIES
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ProviderConnection, SocialAccount
from apps.publishing.models import (
    PublishedPost,
    PublishAttempt,
    PublishTask,
    publishing_writes,
)
from apps.publishing.services import (
    PublishingConflict,
    create_publish_task,
    execute_publish_task,
    retry_publish_task,
)
from integrations.platforms.base import OfficialPublishResult


class RecordingConnector:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def provider_request_fingerprint(self, request):
        from integrations.platforms.buffer_connector import _provider_identity_fingerprint

        return _provider_identity_fingerprint({
            "channelId": request.provider_account_id,
            "mode": "shareNow",
            "schedulingType": "automatic",
            "text": request.payload["commentary"],
            "assets": [],
        })


def _buffer_account(context, monkeypatch):
    platform = context["platform"]
    monkeypatch.setitem(CONNECTOR_CAPABILITIES, platform.code, frozenset({AccountCapability.PUBLISH}))
    connection = ProviderConnection.objects.create(
        organization=context["organization"],
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer/connected",
        external_id="buffer-org-1",
        display_name="Buffer Org",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
    account = SocialAccount.objects.create(
        organization=context["organization"],
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-1",
        external_id="linkedin-page-1",
        display_name="LinkedIn via Buffer",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        status=SocialAccount.Status.ACTIVE,
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )
    return account, connection


def _runtime(monkeypatch, connector):
    from apps.publishing import services

    registry = SimpleNamespace(resolve=lambda account: connector)
    monkeypatch.setattr(
        services,
        "get_social_provider_runtime",
        lambda: SimpleNamespace(connector_registry=registry),
    )
    monkeypatch.setattr(
        services,
        "build_publish_payload",
        lambda **kwargs: {"commentary": "Body"},
    )


def test_buffer_acceptance_becomes_submitted_without_published_post(
    publishing_context, monkeypatch,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-post-1")
    )
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-submit-1",
        actor=publishing_context["actor"],
    )

    assert execute_publish_task(task.id) is None

    task.refresh_from_db()
    publishing_context["content"].refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    assert task.status == PublishTask.Status.SUBMITTED
    assert attempt.status == PublishAttempt.Status.SUBMITTED
    assert task.provider_submission_id == attempt.provider_submission_id == "buffer-post-1"
    assert publishing_context["content"].status == PlatformContent.Status.APPROVED
    assert not PublishedPost.objects.filter(task=task).exists()
    assert len(connector.requests) == 1
    request = connector.requests[0]
    assert request.provider_account_id == "buffer-channel-1"
    assert request.credential_reference == "vault://buffer/connected"
    assert "vault://buffer/connected" not in repr(request)

    execute_publish_task(task.id)
    assert len(connector.requests) == 1


def test_buffer_request_fingerprint_is_persisted_before_provider_call(
    publishing_context, monkeypatch,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)

    class InspectingConnector(RecordingConnector):
        def provider_request_fingerprint(self, request):
            return "a" * 64

        def publish(self, request):
            task = PublishTask.objects.get(pk=request.idempotency_key)
            attempt = PublishAttempt.objects.get(task=task)
            assert task.provider_request_fingerprint == "a" * 64
            assert attempt.provider_request_fingerprint == "a" * 64
            return super().publish(request)

    connector = InspectingConnector(
        OfficialPublishResult(status="SUBMITTED", submission_id="buffer-post-fingerprint")
    )
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"], account=account,
        idempotency_key="buffer-fingerprint-before-call",
        actor=publishing_context["actor"],
    )

    execute_publish_task(task.id)

    task.refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    assert task.provider_request_fingerprint == attempt.provider_request_fingerprint == "a" * 64


def test_unclassified_exception_after_provider_call_is_unknown_and_not_retryable(
    publishing_context, monkeypatch,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(RuntimeError("response parser failed after submit"))
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-runtime-after-call",
        actor=publishing_context["actor"],
    )

    execute_publish_task(task.id)

    task.refresh_from_db()
    attempt = PublishAttempt.objects.get(task=task)
    assert len(connector.requests) == 1
    assert task.provider_call_started_at is not None
    assert task.status == PublishTask.Status.SUBMISSION_UNKNOWN
    assert attempt.status == PublishAttempt.Status.SUBMISSION_UNKNOWN
    assert task.last_error["code"] == "OUTCOME_UNKNOWN"
    with pytest.raises(PublishingConflict, match="reconciliation, not retry"):
        retry_publish_task(task, actor=publishing_context["actor"])


@pytest.mark.parametrize(
    "blocking_status",
    [
        PublishTask.Status.SCHEDULED,
        PublishTask.Status.QUEUED,
        PublishTask.Status.RUNNING,
        PublishTask.Status.SUBMITTED,
        PublishTask.Status.SUBMISSION_UNKNOWN,
        PublishTask.Status.SUCCEEDED,
    ],
)
def test_different_idempotency_key_cannot_duplicate_live_content_account_submission(
    publishing_context, monkeypatch, blocking_status,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    first = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key=f"buffer-first-{blocking_status}",
        actor=publishing_context["actor"],
    )
    with publishing_writes():
        PublishTask.objects.filter(pk=first.pk).update(status=blocking_status)

    with pytest.raises(PublishingConflict, match="already has a publish task"):
        create_publish_task(
            content=publishing_context["content"],
            account=account,
            idempotency_key=f"buffer-second-{blocking_status}",
            actor=publishing_context["actor"],
        )

    assert PublishTask.objects.filter(
        platform_content=publishing_context["content"], social_account=account,
    ).count() == 1


def test_database_rejects_raced_live_content_account_submission(
    publishing_context, monkeypatch,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    first = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-race-first",
        actor=publishing_context["actor"],
    )

    with pytest.raises(IntegrityError), transaction.atomic(), publishing_writes():
        PublishTask.objects.create(
            organization=first.organization,
            platform_content=first.platform_content,
            content_version=first.content_version,
            social_account=first.social_account,
            platform=first.platform,
            connector_code=first.connector_code,
            idempotency_key="buffer-race-second",
            request_fingerprint=first.request_fingerprint,
            status=PublishTask.Status.QUEUED,
            created_by=publishing_context["actor"],
        )


def test_service_translates_concurrent_live_submission_race_to_conflict(
    publishing_context, monkeypatch,
):
    from apps.publishing import services

    account, _connection = _buffer_account(publishing_context, monkeypatch)
    first = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-concurrent-first",
        actor=publishing_context["actor"],
    )
    lookups = iter([None, first])
    monkeypatch.setattr(
        services,
        "_find_blocking_publish_task",
        lambda **_kwargs: next(lookups),
        raising=False,
    )

    with pytest.raises(PublishingConflict, match="already has a publish task"):
        create_publish_task(
            content=publishing_context["content"],
            account=account,
            idempotency_key="buffer-concurrent-second",
            actor=publishing_context["actor"],
        )

    assert PublishTask.objects.filter(
        platform_content=publishing_context["content"], social_account=account,
    ).count() == 1


def _two_failed_buffer_tasks(publishing_context, monkeypatch):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(
        OfficialPublishResult(status="FAILED", error_code="VALIDATION_REJECTED")
    )
    _runtime(monkeypatch, connector)
    tasks = []
    for suffix in ("first", "second"):
        task = create_publish_task(
            content=publishing_context["content"],
            account=account,
            idempotency_key=f"buffer-retry-{suffix}",
            actor=publishing_context["actor"],
        )
        execute_publish_task(task.id)
        task.refresh_from_db()
        assert task.status == PublishTask.Status.FAILED
        tasks.append(task)
    return tasks


def test_second_failed_task_retry_conflicts_with_first_live_retry(
    publishing_context, monkeypatch,
):
    first, second = _two_failed_buffer_tasks(publishing_context, monkeypatch)

    assert retry_publish_task(
        first, actor=publishing_context["actor"]
    ).status == PublishTask.Status.QUEUED
    with pytest.raises(PublishingConflict, match="already has a publish task"):
        retry_publish_task(second, actor=publishing_context["actor"])

    second.refresh_from_db()
    assert second.status == PublishTask.Status.FAILED


def test_concurrent_retry_constraint_race_becomes_publish_conflict(
    publishing_context, monkeypatch,
):
    from apps.publishing import services

    first, second = _two_failed_buffer_tasks(publishing_context, monkeypatch)
    retry_publish_task(first, actor=publishing_context["actor"])
    lookups = iter([None, first])
    monkeypatch.setattr(
        services,
        "_find_blocking_publish_task",
        lambda **_kwargs: next(lookups),
    )

    with pytest.raises(PublishingConflict, match="already has a publish task"):
        retry_publish_task(second, actor=publishing_context["actor"])

    second.refresh_from_db()
    assert second.status == PublishTask.Status.FAILED


@pytest.mark.parametrize(
    ("result", "expected_status", "expected_error"),
    [
        (
            OfficialPublishResult(status="FAILED", error_code="OUTCOME_UNKNOWN"),
            PublishTask.Status.SUBMISSION_UNKNOWN,
            "OUTCOME_UNKNOWN",
        ),
        (
            OfficialPublishResult(status="FAILED", error_code="VALIDATION_REJECTED"),
            PublishTask.Status.FAILED,
            "VALIDATION_REJECTED",
        ),
        (
            OfficialPublishResult(status="FAILED", error_code="BUFFER_PROVIDER_CAPACITY"),
            PublishTask.Status.FAILED,
            "BUFFER_PROVIDER_CAPACITY",
        ),
        (
            OfficialPublishResult(status="FAILED", error_code="REAUTHORIZATION_REQUIRED"),
            PublishTask.Status.FAILED,
            "REAUTHORIZATION_REQUIRED",
        ),
        (
            OfficialPublishResult(
                status="FAILED", error_code="RATE_LIMITED", retry_after_seconds=42,
            ),
            PublishTask.Status.FAILED,
            "RATE_LIMITED",
        ),
    ],
)
def test_buffer_results_map_to_safe_publish_states(
    publishing_context, monkeypatch, result, expected_status, expected_error,
):
    account, _connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(result)
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key=f"buffer-result-{expected_error}",
        actor=publishing_context["actor"],
    )

    execute_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == expected_status
    assert task.last_error["code"] == expected_error
    if expected_error == "RATE_LIMITED":
        assert task.retry_not_before is not None
    assert not PublishedPost.objects.filter(task=task).exists()


def test_disconnected_buffer_connection_is_rejected_before_network(
    publishing_context, monkeypatch,
):
    account, connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(
        OfficialPublishResult(status="SUBMITTED", submission_id="must-not-happen")
    )
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-disconnected",
        actor=publishing_context["actor"],
    )
    ProviderConnection.objects.filter(pk=connection.pk).update(
        connection_state=ProviderConnection.ConnectionState.DISCONNECTED,
        credential_reference="",
    )

    execute_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "PUBLISH_NOT_ELIGIBLE"
    assert connector.requests == []


def test_cross_organization_buffer_connection_is_rejected_before_network(
    publishing_context, monkeypatch,
):
    from apps.identity.models import Organization

    account, _connection = _buffer_account(publishing_context, monkeypatch)
    connector = RecordingConnector(
        OfficialPublishResult(status="SUBMITTED", submission_id="must-not-happen")
    )
    _runtime(monkeypatch, connector)
    task = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="buffer-cross-org",
        actor=publishing_context["actor"],
    )
    foreign_org = Organization.objects.create(name="Foreign", slug="foreign-buffer")
    foreign = ProviderConnection.objects.create(
        organization=foreign_org,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer/foreign",
        external_id="foreign-org",
        display_name="Foreign Buffer",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
    SocialAccount.objects.filter(pk=account.pk).update(provider_connection=foreign)

    execute_publish_task(task.id)

    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "PUBLISH_NOT_ELIGIBLE"
    assert connector.requests == []
