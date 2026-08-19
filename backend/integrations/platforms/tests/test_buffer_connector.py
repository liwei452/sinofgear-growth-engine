from __future__ import annotations

import pytest

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.buffer_client import BufferGraphQLResponse
from integrations.platforms.buffer_connector import BufferConnector
from integrations.platforms.buffer_types import (
    BufferDiscoveryRequest,
    BufferErrorCode,
    BufferRateLimitResult,
)
from integrations.platforms.token_store import OAuthTokenSet


class FakeTokenStore:
    def __init__(self, token="buffer-token"):
        self.token = token
        self.resolve_calls = []
        self.write_calls = []

    def resolve(self, reference):
        self.resolve_calls.append(reference)
        return OAuthTokenSet(access_token=self.token)

    def store(self, *args, **kwargs):
        self.write_calls.append("store")

    def bind(self, *args, **kwargs):
        self.write_calls.append("bind")

    def replace(self, *args, **kwargs):
        self.write_calls.append("replace")

    def delete(self, *args, **kwargs):
        self.write_calls.append("delete")


class FailingTokenStore:
    def resolve(self, reference):
        raise ConnectorConfigurationRequired("not configured")


class FakeClient:
    def __init__(self, account_data=None, channels_data=None):
        self.account_data = account_data
        self.channels_data = channels_data
        self.fetched_account_tokens = []
        self.fetched_channel_orgs = []

    def fetch_account(self, token):
        self.fetched_account_tokens.append(token)
        return BufferGraphQLResponse(
            data=self.account_data, rate_limit=BufferRateLimitResult()
        )

    def fetch_channels(self, token, organization_id):
        self.fetched_channel_orgs.append((token, organization_id))
        return BufferGraphQLResponse(
            data=self.channels_data, rate_limit=BufferRateLimitResult()
        )


def _request(expected_org_id="org-1", credential="vault://buffer/acme"):
    return BufferDiscoveryRequest(
        credential_reference=credential,
        expected_organization_id=expected_org_id,
    )


def _account(*organizations):
    return {"account": {"id": "acct-1", "name": "Acme", "organizations": list(organizations)}}


def _org(org_id, name="Acme Org"):
    return {"id": org_id, "name": name}


def _channel(**overrides):
    base = {
        "id": "ch-1",
        "organizationId": "org-1",
        "service": "linkedin",
        "serviceId": "li-page-1",
        "name": "Acme Page",
        "displayName": "Acme LinkedIn",
        "avatar": "https://cdn.example.com/a.png",
        "externalLink": "https://example.com/company/acme",
        "type": "Page",
        "isDisconnected": False,
        "isLocked": False,
        "isQueuePaused": False,
        "allowedActions": ["CREATE_POSTS"],
        "products": ["PUBLISH"],
        "scopes": ["pages_manage_posts"],
    }
    base.update(overrides)
    return base


def _connector(token_store=None, client=None):
    return BufferConnector(
        client=client or FakeClient(),
        token_store=token_store or FakeTokenStore(),
    )


def test_probe_returns_account_and_organizations():
    client = FakeClient(account_data=_account(_org("org-1"), _org("org-2")))
    token_store = FakeTokenStore()
    result = _connector(token_store=token_store, client=client).probe_connection(_request())

    assert result.ok is True
    assert result.account.id == "acct-1"
    assert [org.provider_organization_id for org in result.account.organizations] == [
        "org-1",
        "org-2",
    ]
    assert token_store.resolve_calls == ["vault://buffer/acme"]


def test_probe_fails_safely_when_token_store_is_unavailable():
    result = _connector(token_store=FailingTokenStore()).probe_connection(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONFIGURATION_REQUIRED.value


def test_probe_rejects_blank_expected_organization_id():
    result = _connector().probe_connection(_request(expected_org_id="   "))
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONFIGURATION_REQUIRED.value


def test_probe_organization_not_found_is_safe_failure():
    client = FakeClient(account_data=_account(_org("org-1")))
    result = _connector(client=client).probe_connection(_request(expected_org_id="missing"))
    assert result.ok is False
    assert result.error_code == BufferErrorCode.ORGANIZATION_NOT_FOUND.value


def test_probe_duplicate_organization_id_is_contract_error():
    client = FakeClient(account_data=_account(_org("org-1"), _org(" org-1 ")))
    result = _connector(client=client).probe_connection(_request(expected_org_id="org-1"))
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_probe_normalizes_and_strips_account_and_organization_ids():
    client = FakeClient(
        account_data={
            "account": {
                "id": " acct-1 ",
                "name": "Acme",
                "organizations": [{"id": " org-1 ", "name": "Acme Org"}],
            }
        }
    )
    result = _connector(client=client).probe_connection(_request(expected_org_id=" org-1 "))

    assert result.ok is True
    assert result.account.id == "acct-1"
    assert result.account.organizations[0].provider_organization_id == "org-1"


@pytest.mark.parametrize("org_id", ["", "   ", "x" * 256])
def test_probe_rejects_invalid_organization_id(org_id):
    client = FakeClient(account_data=_account({"id": org_id, "name": "Acme Org"}))
    result = _connector(client=client).probe_connection(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


@pytest.mark.parametrize("org_name", [123, "x" * 256])
def test_probe_rejects_invalid_organization_name(org_name):
    client = FakeClient(account_data=_account({"id": "org-1", "name": org_name}))
    result = _connector(client=client).probe_connection(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_probe_accepts_null_organization_name():
    client = FakeClient(account_data=_account({"id": "org-1", "name": None}))
    result = _connector(client=client).probe_connection(_request())
    assert result.ok is True
    assert result.account.organizations[0].name == ""


def test_discover_selects_exact_organization_by_id():
    client = FakeClient(
        account_data=_account(_org("org-1"), _org("org-2")),
        channels_data={"channels": []},
    )
    result = _connector(client=client).discover_channels(_request(expected_org_id="org-2"))

    assert result.ok is True
    assert result.provider_organization_id == "org-2"
    assert client.fetched_channel_orgs == [("buffer-token", "org-2")]


def test_discover_organization_not_found_is_safe_failure():
    client = FakeClient(account_data=_account(_org("org-1")))
    result = _connector(client=client).discover_channels(_request(expected_org_id="missing"))

    assert result.ok is False
    assert result.error_code == BufferErrorCode.ORGANIZATION_NOT_FOUND.value


def test_discover_rejects_blank_expected_organization_id():
    result = _connector().discover_channels(_request(expected_org_id="   "))
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONFIGURATION_REQUIRED.value


def test_supported_services_map_to_internal_platform_codes():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [
                _channel(id="li-1", serviceId="li-page", service="linkedin"),
                _channel(id="fb-1", serviceId="fb-page", service="facebook"),
                _channel(id="ig-1", serviceId="ig-page", service="instagram"),
            ]
        },
    )
    result = _connector(client=client).discover_channels(_request())

    by_platform = {channel.platform_code: channel for channel in result.channels}
    assert set(by_platform) == {"LINKEDIN", "FACEBOOK", "INSTAGRAM"}
    assert by_platform["LINKEDIN"].external_id == "li-page"
    assert by_platform["FACEBOOK"].provider_account_id == "fb-1"


def test_channel_fields_are_mapped_and_display_name_falls_back_to_name():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [
                _channel(id="ch-1", serviceId="svc-1", name="Handle Name", displayName=None)
            ]
        },
    )
    result = _connector(client=client).discover_channels(_request())

    channel = result.channels[0]
    assert channel.provider_account_id == "ch-1"
    assert channel.external_id == "svc-1"
    assert channel.display_name == "Handle Name"
    assert channel.provider == "BUFFER"


def test_connection_state_flags_are_preserved():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [
                _channel(
                    isDisconnected=True,
                    isLocked=True,
                    isQueuePaused=True,
                )
            ]
        },
    )
    result = _connector(client=client).discover_channels(_request())

    channel = result.channels[0]
    assert channel.is_disconnected is True
    assert channel.is_locked is True
    assert channel.is_queue_paused is True


def test_unsupported_service_goes_to_ignored_channels():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [_channel(id="tw-1", serviceId="tw-page", service="twitter")]
        },
    )
    result = _connector(client=client).discover_channels(_request())

    assert result.channels == ()
    assert len(result.ignored_channels) == 1
    assert result.ignored_channels[0].provider_account_id == "tw-1"
    assert result.ignored_channels[0].service == "twitter"


def test_unknown_service_is_not_uppercased_into_platform_code():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [_channel(id="tw-1", serviceId="tw-page", service="twitter")]
        },
    )
    result = _connector(client=client).discover_channels(_request())

    assert result.channels == ()
    assert result.ignored_channels[0].service == "twitter"


def test_duplicate_channel_id_is_contract_error():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [
                _channel(id="dup", serviceId="svc-a"),
                _channel(id="dup", serviceId="svc-b"),
            ]
        },
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_duplicate_service_id_within_platform_is_contract_error():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={
            "channels": [
                _channel(id="ch-a", serviceId="same-page"),
                _channel(id="ch-b", serviceId="same-page"),
            ]
        },
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_channel_organization_id_mismatch_is_contract_error():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": [_channel(organizationId="other-org")]},
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


@pytest.mark.parametrize("field", ["id", "serviceId", "name"])
@pytest.mark.parametrize("bad_value", [123, "   ", "x" * 256])
def test_non_string_blank_or_too_long_fields_are_rejected(field, bad_value):
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": [_channel(**{field: bad_value})]},
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


@pytest.mark.parametrize("field", ["allowedActions", "products", "scopes"])
def test_bounded_string_list_fields_are_enforced(field):
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": [_channel(**{field: ["ok", 123]})]},
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_non_bool_state_flags_are_rejected():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": [_channel(isDisconnected="yes")]},
    )
    result = _connector(client=client).discover_channels(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_account_null_is_contract_error():
    client = FakeClient(account_data={"account": None})
    result = _connector(client=client).probe_connection(_request())
    assert result.ok is False
    assert result.error_code == BufferErrorCode.CONTRACT_ERROR.value


def test_connector_only_reads_token_store_and_never_writes():
    token_store = FakeTokenStore()
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": []},
    )
    _connector(token_store=token_store, client=client).discover_channels(_request())

    assert token_store.resolve_calls == ["vault://buffer/acme"]
    assert token_store.write_calls == []


def test_connector_normalizes_stripped_provider_account_id():
    client = FakeClient(
        account_data=_account(_org("org-1")),
        channels_data={"channels": [_channel(id=" ch-1 ", serviceId=" svc-1 ")]},
    )
    result = _connector(client=client).discover_channels(_request())

    assert result.channels[0].provider_account_id == "ch-1"
    assert result.channels[0].external_id == "svc-1"
