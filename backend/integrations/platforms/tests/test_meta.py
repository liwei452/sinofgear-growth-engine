import pytest

from integrations.platforms.base import OfficialPublishRequest
from integrations.platforms.meta import MetaConnector
from integrations.platforms.token_store import OAuthTokenSet
from integrations.platforms.transport import HttpResponse


class TokenStore:
    def resolve(self, reference: str) -> OAuthTokenSet:
        assert reference == "vault://meta/acme"
        return OAuthTokenSet(access_token="meta-access-token")


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def request(channel: str, payload: dict) -> OfficialPublishRequest:
    return OfficialPublishRequest(
        channel=channel,
        account_external_id="account-123",
        credential_reference="vault://meta/acme",
        payload=payload,
        idempotency_key="batch-123",
        consent={},
    )


def test_facebook_page_publish_uses_official_page_feed_contract() -> None:
    transport = RecordingTransport([HttpResponse(200, {"id": "page_456"}, {})])
    result = MetaConnector(transport=transport, token_store=TokenStore()).publish(
        request("FACEBOOK", {"message": "Factory proof", "link": "https://example.com/proof"})
    )

    assert result.status == "SUCCEEDED"
    assert result.external_id == "page_456"
    method, url, kwargs = transport.requests[0]
    assert (method, url) == ("POST", "https://graph.facebook.com/v23.0/account-123/feed")
    assert kwargs["headers"]["Authorization"] == "Bearer meta-access-token"
    assert kwargs["json"] == {"message": "Factory proof", "link": "https://example.com/proof"}


def test_instagram_publish_creates_checks_and_publishes_media_container() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"id": "container-1"}, {}),
        HttpResponse(200, {"status_code": "FINISHED"}, {}),
        HttpResponse(200, {"id": "ig-post-1"}, {}),
    ])
    result = MetaConnector(transport=transport, token_store=TokenStore()).publish(
        request("INSTAGRAM", {
            "caption": "Precision gear proof",
            "video_url": "https://cdn.example.com/gear.mp4",
            "media_type": "REELS",
        })
    )

    assert result.status == "SUCCEEDED"
    assert result.external_id == "ig-post-1"
    assert [(method, url) for method, url, _ in transport.requests] == [
        ("POST", "https://graph.facebook.com/v23.0/account-123/media"),
        ("GET", "https://graph.facebook.com/v23.0/container-1"),
        ("POST", "https://graph.facebook.com/v23.0/account-123/media_publish"),
    ]
    assert transport.requests[2][2]["json"] == {"creation_id": "container-1"}
    assert transport.requests[0][2]["json"] == {
        "caption": "Precision gear proof",
        "video_url": "https://cdn.example.com/gear.mp4",
        "media_type": "REELS",
    }


def test_instagram_image_publish_uses_image_container() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"id": "container-2"}, {}),
        HttpResponse(200, {"status_code": "FINISHED"}, {}),
        HttpResponse(200, {"id": "ig-post-2"}, {}),
    ])

    result = MetaConnector(transport=transport, token_store=TokenStore()).publish(
        request("INSTAGRAM", {
            "caption": "Gear close-up",
            "image_url": "https://cdn.example.com/gear.png",
            "media_type": "IMAGE",
        })
    )

    assert result.status == "SUCCEEDED"
    assert result.external_id == "ig-post-2"
    assert transport.requests[0][2]["json"] == {
        "caption": "Gear close-up",
        "image_url": "https://cdn.example.com/gear.png",
    }


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [(400, "VALIDATION_REJECTED", False), (401, "REAUTHORIZATION_REQUIRED", False),
     (403, "VALIDATION_REJECTED", False), (429, "RATE_LIMITED", True),
     (503, "PROVIDER_UNAVAILABLE", True)],
)
def test_meta_errors_are_normalized_without_leaking_tokens(
    status_code: int, expected_code: str, retryable: bool,
) -> None:
    transport = RecordingTransport([
        HttpResponse(status_code, {"error": {"message": "meta-access-token rejected"}}, {"Retry-After": "17"})
    ])

    result = MetaConnector(transport=transport, token_store=TokenStore()).publish(
        request("FACEBOOK", {"message": "Factory proof"})
    )

    assert result.error_code == expected_code
    assert result.retryable is retryable
    assert result.retry_after_seconds == (17 if status_code == 429 else None)
    assert "meta-access-token" not in result.error_message
