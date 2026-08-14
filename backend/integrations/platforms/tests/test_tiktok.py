import pytest

from integrations.platforms.base import OfficialPublishRequest
from integrations.platforms.tiktok import TikTokConnector
from integrations.platforms.token_store import OAuthTokenSet
from integrations.platforms.transport import HttpResponse


class TokenStore:
    def resolve(self, reference: str) -> OAuthTokenSet:
        return OAuthTokenSet(access_token="tiktok-token")


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def publish_request(consent: dict) -> OfficialPublishRequest:
    return OfficialPublishRequest(
        channel="TIKTOK",
        account_external_id="creator-1",
        credential_reference="vault://tiktok/acme",
        payload={
            "title": "30 second inspection proof",
            "video_url": "https://cdn.example.com/inspection.mp4",
        },
        idempotency_key="batch-tiktok",
        consent=consent,
    )


def test_tiktok_queries_creator_before_direct_post_and_preserves_consent() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"data": {"privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"]}}, {}),
        HttpResponse(200, {"data": {"publish_id": "publish-1"}}, {}),
    ])
    connector = TikTokConnector(
        transport=transport, token_store=TokenStore(), client_audited=True,
    )

    result = connector.publish(publish_request({
        "explicit": True,
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "allow_comment": True,
        "allow_duet": False,
        "allow_stitch": False,
    }))

    assert result.status == "SUCCEEDED"
    assert result.external_id == "publish-1"
    assert [url for _method, url, _kwargs in transport.requests] == [
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
    ]
    post_info = transport.requests[1][2]["json"]["post_info"]
    assert post_info == {
        "title": "30 second inspection proof",
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "disable_comment": False,
        "disable_duet": True,
        "disable_stitch": True,
    }


def test_tiktok_requires_explicit_consent_before_any_provider_request() -> None:
    transport = RecordingTransport([])

    result = TikTokConnector(
        transport=transport, token_store=TokenStore(), client_audited=True,
    ).publish(publish_request({"privacy_level": "PUBLIC_TO_EVERYONE"}))

    assert result.error_code == "VALIDATION_REJECTED"
    assert transport.requests == []


def test_unaudited_tiktok_client_cannot_claim_public_publication() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"data": {"privacy_level_options": ["SELF_ONLY"]}}, {}),
        HttpResponse(200, {"data": {"publish_id": "private-1"}}, {}),
    ])

    result = TikTokConnector(
        transport=transport, token_store=TokenStore(), client_audited=False,
    ).publish(publish_request({
        "explicit": True,
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "allow_comment": True,
        "allow_duet": True,
        "allow_stitch": True,
    }))

    assert result.status == "SUCCEEDED_PRIVATE"
    assert result.external_url == ""
    assert transport.requests[1][2]["json"]["post_info"]["privacy_level"] == "SELF_ONLY"


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [(401, "REAUTHORIZATION_REQUIRED", False), (429, "RATE_LIMITED", True), (500, "PROVIDER_UNAVAILABLE", True)],
)
def test_tiktok_provider_errors_are_normalized(
    status_code: int, expected_code: str, retryable: bool,
) -> None:
    transport = RecordingTransport([HttpResponse(status_code, {"error": {"message": "tiktok-token"}}, {})])

    result = TikTokConnector(
        transport=transport, token_store=TokenStore(), client_audited=True,
    ).publish(publish_request({
        "explicit": True, "privacy_level": "SELF_ONLY",
        "allow_comment": False, "allow_duet": False, "allow_stitch": False,
    }))

    assert result.error_code == expected_code
    assert result.retryable is retryable
    assert "tiktok-token" not in result.error_message
