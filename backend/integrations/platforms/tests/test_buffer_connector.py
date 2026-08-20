from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json

import pytest
from django.conf import settings

from integrations.platforms.base import ConnectorConfigurationRequired, OfficialPublishRequest
from integrations.platforms.buffer_client import BufferGraphQLResponse
from integrations.platforms.buffer_connector import BufferConnector, provider_request_fingerprint
from integrations.platforms.buffer_types import (
    BufferApiError,
    BufferDiscoveryRequest,
    BufferErrorCode,
    BufferRateLimitResult,
    BufferPostQueryRequest,
    BufferUnknownMatchRequest,
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
        self.created_posts = []
        self.create_post_data = None
        self.create_post_error = None
        self.post_data = None
        self.post_error = None
        self.fetched_posts = []
        self.post_pages = []
        self.fetched_post_pages = []

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

    def create_post(self, token, post_input):
        self.created_posts.append((token, post_input))
        if self.create_post_error is not None:
            raise self.create_post_error
        return BufferGraphQLResponse(
            data=self.create_post_data, rate_limit=BufferRateLimitResult()
        )

    def fetch_post(self, token, post_id):
        self.fetched_posts.append((token, post_id))
        if self.post_error is not None:
            raise self.post_error
        return BufferGraphQLResponse(
            data=self.post_data, rate_limit=BufferRateLimitResult()
        )

    def fetch_posts(self, token, **kwargs):
        self.fetched_post_pages.append((token, kwargs))
        return BufferGraphQLResponse(
            data=self.post_pages[len(self.fetched_post_pages) - 1],
            rate_limit=BufferRateLimitResult(),
        )


def test_fetch_post_normalizes_strict_official_contract():
    client = FakeClient()
    client.post_data = {
        "post": {
            "id": "post-1", "channelId": "ch-1", "channelService": "linkedin",
            "status": "sent", "dueAt": None, "sentAt": "2026-08-20T01:02:03Z",
            "externalLink": "https://www.linkedin.com/feed/update/1",
            "createdAt": "2026-08-20T01:00:00Z", "updatedAt": "2026-08-20T01:02:03Z",
        }
    }
    connector = BufferConnector(client, FakeTokenStore())

    request = BufferPostQueryRequest(
        credential_reference="vault://buffer/acme", provider_submission_id="post-1"
    )
    assert "vault://buffer/acme" not in repr(request)
    result = connector.fetch_post(request)

    assert result.ok is True
    assert result.observation.post_id == "post-1"
    assert result.observation.status == "sent"
    assert result.observation.sent_at.isoformat() == "2026-08-20T01:02:03+00:00"
    assert client.fetched_posts == [("buffer-token", "post-1")]


def test_provider_request_fingerprint_uses_final_input_but_not_credential():
    base = OfficialPublishRequest(
        channel="LINKEDIN",
        account_external_id="local-account",
        provider_account_id="buffer-channel-1",
        credential_reference="vault://buffer/first",
        payload={"commentary": " Final text ", "image_url": "https://cdn.example.com/a.png"},
        idempotency_key="task-1",
        consent={},
    )
    rotated = OfficialPublishRequest(
        channel=base.channel,
        account_external_id=base.account_external_id,
        provider_account_id=base.provider_account_id,
        credential_reference="vault://buffer/rotated",
        payload=base.payload,
        idempotency_key=base.idempotency_key,
        consent=base.consent,
    )
    changed_text = OfficialPublishRequest(
        channel=base.channel,
        account_external_id=base.account_external_id,
        provider_account_id=base.provider_account_id,
        credential_reference=base.credential_reference,
        payload={**base.payload, "commentary": "Different"},
        idempotency_key=base.idempotency_key,
        consent=base.consent,
    )

    fingerprint = provider_request_fingerprint(base)
    expected_identity = {
        "channelId": "buffer-channel-1",
        "mode": "shareNow",
        "schedulingType": "automatic",
        "needsApproval": False,
        "text": "Final text",
        "assets": [{"type": "image", "source": "https://cdn.example.com/a.png"}],
    }
    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        b"buffer-provider-request-v1\x00"
        + json.dumps(
            expected_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert len(fingerprint) == 64
    assert set(fingerprint) <= set("0123456789abcdef")
    assert fingerprint == expected
    assert fingerprint == provider_request_fingerprint(rotated)
    assert fingerprint != provider_request_fingerprint(changed_text)
    assert "vault" not in fingerprint


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("channelService", "unsupported"),
        ("sentAt", "not-a-time"),
        ("externalLink", "file:///secret"),
    ],
)
def test_fetch_post_rejects_malformed_contract(field, value):
    client = FakeClient()
    client.post_data = {
        "post": {
            "id": "post-1", "channelId": "ch-1", "channelService": "linkedin",
            "status": "sent", "dueAt": None, "sentAt": "2026-08-20T01:02:03Z",
            "externalLink": "https://example.com/post/1", "createdAt": None, "updatedAt": None,
            field: value,
        }
    }
    result = BufferConnector(client, FakeTokenStore()).fetch_post(
        BufferPostQueryRequest(
            credential_reference="vault://buffer/acme", provider_submission_id="post-1"
        )
    )
    assert result.ok is False
    assert result.error_code == "BUFFER_CONTRACT_ERROR"


def _candidate_page(post_id, *, has_next, cursor):
    return {
        "posts": {
            "edges": [
                {
                    "cursor": f"edge-{post_id}",
                    "node": {
                        "id": post_id,
                        "channelId": "ch-1",
                        "channelService": "linkedin",
                        "status": "scheduled",
                        "text": "Final text",
                        "createdAt": "2026-08-20T01:05:00Z",
                        "dueAt": "2026-08-20T02:00:00Z",
                        "sentAt": None,
                        "schedulingType": "automatic",
                        "shareMode": "shareNow",
                        "assets": [
                            {
                                "type": "image",
                                "mimeType": "image/png",
                                "source": "https://cdn.example.com/a.png",
                            }
                        ],
                    },
                }
            ],
            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        }
    }


def test_unknown_match_search_normalizes_candidates_and_stops_after_three_pages():
    client = FakeClient()
    client.post_pages = [
        _candidate_page("post-1", has_next=True, cursor="page-1"),
        _candidate_page("post-2", has_next=True, cursor="page-2"),
        _candidate_page("post-3", has_next=True, cursor="page-3"),
    ]
    request = BufferUnknownMatchRequest(
        credential_reference="vault://buffer/acme",
        provider_organization_id="org-1",
        provider_account_id="ch-1",
        window_start=datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 20, 1, 17, tzinfo=timezone.utc),
    )
    assert "vault://buffer/acme" not in repr(request)

    result = BufferConnector(client, FakeTokenStore()).search_post_candidates(request)

    assert result.ok is True
    assert result.truncated is True
    assert [candidate.post_id for candidate in result.candidates] == ["post-1", "post-2", "post-3"]
    assert result.candidates[0].assets[0].asset_type == "image"
    assert result.candidates[0].assets[0].source == "https://cdn.example.com/a.png"
    assert [call[1]["after"] for call in client.fetched_post_pages] == [None, "page-1", "page-2"]
    assert len(result.candidates) == 3


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


def _publish_request(channel="LINKEDIN", payload=None):
    return OfficialPublishRequest(
        channel=channel,
        account_external_id="legacy-external-id",
        provider_account_id="ch-1",
        credential_reference="vault://buffer/acme",
        payload=payload or {"commentary": "Precision gears"},
        idempotency_key="task-1",
        consent={},
    )


def _post_success(**overrides):
    post = {
        "id": "buffer-post-1", "channelId": "ch-1", "status": "scheduled",
        "dueAt": None, "createdAt": "2026-08-20T00:00:00Z",
    }
    post.update(overrides)
    return {"createPost": {"__typename": "PostActionSuccess", "post": post}}


@pytest.mark.parametrize(
    ("channel", "payload", "expected"),
    [
        ("LINKEDIN", {"commentary": "LinkedIn text"}, {
            "channelId": "ch-1", "text": "LinkedIn text",
            "schedulingType": "automatic", "mode": "shareNow",
            "assets": [], "needsApproval": False,
        }),
        ("FACEBOOK", {"message": "Facebook text", "image_url": "https://cdn.example/a.jpg"}, {
            "channelId": "ch-1", "text": "Facebook text",
            "schedulingType": "automatic", "mode": "shareNow",
            "needsApproval": False,
            "assets": [{"image": {"url": "https://cdn.example/a.jpg"}}],
        }),
        ("INSTAGRAM", {"caption": "Instagram image", "image_url": "https://cdn.example/i.jpg", "media_type": "IMAGE"}, {
            "channelId": "ch-1", "text": "Instagram image",
            "schedulingType": "automatic", "mode": "shareNow",
            "needsApproval": False,
            "assets": [{"image": {"url": "https://cdn.example/i.jpg"}}],
        }),
        ("INSTAGRAM", {"caption": "Instagram video", "video_url": "https://cdn.example/v.mp4", "media_type": "REELS"}, {
            "channelId": "ch-1", "text": "Instagram video",
            "schedulingType": "automatic", "mode": "shareNow",
            "needsApproval": False,
            "assets": [{"video": {"url": "https://cdn.example/v.mp4"}}],
        }),
    ],
)
def test_publish_maps_supported_channels_to_buffer_create_post(channel, payload, expected):
    client = FakeClient()
    client.create_post_data = _post_success()

    result = _connector(client=client).publish(_publish_request(channel, payload))

    assert result.status == "SUBMITTED"
    assert result.submission_id == "buffer-post-1"
    assert client.created_posts == [("buffer-token", expected)]


def test_instagram_without_media_fails_before_network():
    client = FakeClient()

    result = _connector(client=client).publish(
        _publish_request("INSTAGRAM", {"caption": "No media"})
    )

    assert result.status == "FAILED"
    assert result.error_code == "VALIDATION_REJECTED"
    assert client.created_posts == []


@pytest.mark.parametrize("channel,text_field", [("LINKEDIN", "commentary"), ("FACEBOOK", "message")])
def test_text_channels_reject_video_before_network(channel, text_field):
    client = FakeClient()

    result = _connector(client=client).publish(
        _publish_request(
            channel,
            {text_field: "No unsupported video", "video_url": "https://cdn.example/v.mp4"},
        )
    )

    assert result.status == "FAILED"
    assert result.error_code == "VALIDATION_REJECTED"
    assert client.created_posts == []


@pytest.mark.parametrize("post_id", ["", "   ", 123, "x" * 256])
def test_invalid_success_identity_is_submission_unknown(post_id):
    client = FakeClient()
    client.create_post_data = _post_success(id=post_id)

    result = _connector(client=client).publish(_publish_request())

    assert result.status == "FAILED"
    assert result.error_code == "OUTCOME_UNKNOWN"


def test_mismatched_success_channel_is_submission_unknown():
    client = FakeClient()
    client.create_post_data = _post_success(channelId="other-channel")

    result = _connector(client=client).publish(_publish_request())

    assert result.error_code == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize(
    ("typename", "error_code"),
    [
        ("InvalidInputError", "VALIDATION_REJECTED"),
        ("LimitReachedError", "BUFFER_PROVIDER_CAPACITY"),
        ("NotFoundError", "BUFFER_CHANNEL_NOT_FOUND"),
    ],
)
def test_explicit_mutation_errors_are_safe_failures(typename, error_code):
    client = FakeClient()
    client.create_post_data = {
        "createPost": {"__typename": typename, "message": "raw provider detail"}
    }

    result = _connector(client=client).publish(_publish_request())

    assert result.status == "FAILED"
    assert result.error_code == error_code
    assert "raw provider detail" not in result.error_message


@pytest.mark.parametrize(
    ("provider_error", "error_code", "retry_after"),
    [
        (BufferErrorCode.AUTHENTICATION_REQUIRED, "REAUTHORIZATION_REQUIRED", None),
        (BufferErrorCode.RATE_LIMITED, "RATE_LIMITED", 41),
        (BufferErrorCode.OUTCOME_UNKNOWN, "OUTCOME_UNKNOWN", None),
        (BufferErrorCode.CHANNEL_NOT_FOUND, "BUFFER_CHANNEL_NOT_FOUND", None),
    ],
)
def test_provider_failures_map_without_leaking_raw_details(
    provider_error, error_code, retry_after,
):
    client = FakeClient()
    client.create_post_error = BufferApiError(
        provider_error,
        message="raw secret provider detail",
        retry_after_seconds=retry_after,
    )

    result = _connector(client=client).publish(_publish_request())

    assert result.error_code == error_code
    assert result.retry_after_seconds == retry_after
    assert "raw secret provider detail" not in result.error_message


def test_stale_credential_reference_fails_without_network_or_secret_disclosure():
    client = FakeClient()
    request = _publish_request()

    result = _connector(token_store=FailingTokenStore(), client=client).publish(request)

    assert result.error_code == "PUBLISH_NOT_ELIGIBLE"
    assert client.created_posts == []
    assert request.credential_reference not in repr(request)


def test_even_sent_success_remains_submitted_until_reconciliation():
    client = FakeClient()
    client.create_post_data = _post_success(status="sent")

    result = _connector(client=client).publish(_publish_request())

    assert result.status == "SUBMITTED"
    assert result.submission_id == "buffer-post-1"


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
