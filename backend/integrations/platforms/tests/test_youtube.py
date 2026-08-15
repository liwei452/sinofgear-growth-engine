from uuid import uuid4

import pytest

from integrations.platforms.base import OfficialPublishRequest
from integrations.platforms.token_store import OAuthTokenSet
from integrations.platforms.transport import HttpResponse
from integrations.platforms.youtube import YouTubeConnector


class TokenStore:
    def resolve(self, reference):
        return OAuthTokenSet(access_token="fixture-youtube-token")


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


class MediaLoader:
    def __init__(self, content=b"fixture-video"):
        self.content = content
        self.calls = []

    def load(self, url, *, max_bytes):
        self.calls.append((url, max_bytes))
        return self.content


def request(**payload_overrides):
    payload = {
        "title": "Factory inspection",
        "description": "Verified gear inspection footage.",
        "video_url": "https://assets.example.com/video.mp4",
    }
    payload.update(payload_overrides)
    return OfficialPublishRequest(
        channel="YOUTUBE",
        account_external_id="channel-1",
        credential_reference="vault://youtube/fixture",
        payload=payload,
        idempotency_key=f"youtube-{uuid4()}",
        consent={"explicit": True, "privacy_status": "private"},
    )


def test_youtube_initializes_and_uploads_bounded_media_idempotently() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {}, {"Location": "https://www.googleapis.com/upload/youtube/v3/session/fixture"}),
        HttpResponse(200, {"id": "video-123"}, {}),
    ])
    media = MediaLoader()
    connector = YouTubeConnector(
        transport=transport, token_store=TokenStore(), media_loader=media,
    )
    publish_request = request()

    result = connector.publish(publish_request)

    assert result.status == "SUCCEEDED_PRIVATE"
    assert result.external_id == "video-123"
    assert result.external_url == "https://www.youtube.com/watch?v=video-123"
    assert transport.requests[0][2]["headers"]["X-Idempotency-Key"] == (
        publish_request.idempotency_key
    )
    assert transport.requests[1][2]["data"] == b"fixture-video"
    assert media.calls == [("https://assets.example.com/video.mp4", 256 * 1024 * 1024)]


@pytest.mark.parametrize(
    "payload",
    [
        {"video_url": "http://assets.example.com/video.mp4"},
        {"title": ""},
        {"title": "x" * 101},
    ],
)
def test_youtube_rejects_invalid_media_or_metadata_before_transport(payload) -> None:
    transport = RecordingTransport([])
    result = YouTubeConnector(
        transport=transport, token_store=TokenStore(), media_loader=MediaLoader(),
    ).publish(request(**payload))
    assert result.error_code == "VALIDATION_REJECTED"
    assert transport.requests == []


def test_youtube_requires_explicit_private_or_public_consent() -> None:
    invalid = request()
    invalid = OfficialPublishRequest(**{**invalid.__dict__, "consent": {}})
    transport = RecordingTransport([])
    result = YouTubeConnector(
        transport=transport, token_store=TokenStore(), media_loader=MediaLoader(),
    ).publish(invalid)
    assert result.error_code == "VALIDATION_REJECTED"
    assert transport.requests == []


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (HttpResponse(429, {}, {"Retry-After": "8"}), "RATE_LIMITED", True),
        (HttpResponse(500, {}, {}), "PROVIDER_UNAVAILABLE", True),
        (TimeoutError(), "OUTCOME_UNKNOWN", True),
    ],
)
def test_youtube_normalizes_initialization_failure(response, code, retryable) -> None:
    result = YouTubeConnector(
        transport=RecordingTransport([response]),
        token_store=TokenStore(),
        media_loader=MediaLoader(),
    ).publish(request())
    assert result.error_code == code
    assert result.retryable is retryable
