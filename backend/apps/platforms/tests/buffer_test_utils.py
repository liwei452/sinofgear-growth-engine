from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import ProviderConnection
from integrations.platforms.buffer_types import (
    BufferAccount,
    BufferChannel,
    BufferDiscoveryResult,
    BufferIgnoredChannel,
    BufferOrganization,
    BufferProbeResult,
)


class FakeTokenStore:
    def __init__(self):
        self.references = []
        self.stored = []
        self.deleted = []

    def store(self, bundle, context):
        reference = f"vault://buffer/fixture/{len(self.stored)}"
        self.stored.append(reference)
        self.references.append(reference)
        return reference

    def resolve(self, reference):
        raise AssertionError(f"Unexpected resolve: {reference}")

    def delete(self, reference):
        self.deleted.append(reference)
        if reference in self.references:
            self.references.remove(reference)


class FakeConnector:
    def __init__(self):
        self.probe_result = None
        self.discover_result = None
        self.probe_calls = []
        self.discover_calls = []
        self.on_discover = None

    def probe_connection(self, request):
        self.probe_calls.append(request)
        return self.probe_result

    def discover_channels(self, request):
        self.discover_calls.append(request)
        if self.on_discover is not None:
            self.on_discover(request)
        return self.discover_result


def authenticated_member(*, organization: Organization, role: Role, prefix: str) -> tuple[APIClient, object]:
    username = f"{prefix}-{uuid.uuid4().hex[:10]}"
    user = get_user_model().objects.create_user(
        username=username, password="correct-horse-battery-staple",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="correct-horse-battery-staple")
    return client, user


def probe_ok(org_id="org-1", name="Acme Org", account_name="Acme") -> BufferProbeResult:
    return BufferProbeResult(
        ok=True,
        account=BufferAccount(
            id="acct-1",
            name=account_name,
            organizations=(BufferOrganization(provider_organization_id=org_id, name=name),),
        ),
        rate_limit=None,
    )


def probe_fail(code: str) -> BufferProbeResult:
    return BufferProbeResult(ok=False, error_code=code, error_message="safe")


def channel(
    *,
    platform_code="LINKEDIN",
    service="linkedin",
    provider_account_id="ch-1",
    external_id="li-page-1",
    **kwargs,
) -> BufferChannel:
    values = dict(
        provider_account_id=provider_account_id,
        external_id=external_id,
        display_name="Acme LinkedIn",
        provider="BUFFER",
        platform_code=platform_code,
        service=service,
        channel_type="Page",
        avatar="https://cdn.example.com/a.png",
        external_link="https://example.com/company/acme",
        organization_id="org-1",
        is_disconnected=False,
        is_locked=False,
        is_queue_paused=False,
        allowed_actions=(),
        products=(),
        scopes=(),
    )
    values.update(kwargs)
    return BufferChannel(**values)


def discover_ok(channels=(), ignored=()) -> BufferDiscoveryResult:
    return BufferDiscoveryResult(
        ok=True,
        provider_organization_id="org-1",
        channels=tuple(channels),
        ignored_channels=tuple(ignored),
        rate_limit=None,
    )


def discover_fail(code: str) -> BufferDiscoveryResult:
    return BufferDiscoveryResult(ok=False, error_code=code, error_message="safe")


def ignored_channel(provider_account_id: str, service: str) -> BufferIgnoredChannel:
    return BufferIgnoredChannel(
        provider_account_id=provider_account_id,
        service=service,
        reason="该平台暂不支持通过 Buffer 同步。",
    )


def connected_connection(organization, *, reference="vault://buffer/existing") -> ProviderConnection:
    return ProviderConnection.objects.create(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference=reference,
        external_id="org-1",
        display_name="Acme Org",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
