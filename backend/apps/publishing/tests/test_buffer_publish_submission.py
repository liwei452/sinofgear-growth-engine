from types import SimpleNamespace

import pytest

from apps.content.models import PlatformContent
from apps.platforms.capabilities import CONNECTOR_CAPABILITIES
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ProviderConnection, SocialAccount
from apps.publishing.models import PublishedPost, PublishAttempt, PublishTask
from apps.publishing.services import create_publish_task, execute_publish_task
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
