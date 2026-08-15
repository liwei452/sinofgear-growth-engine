import pytest

from integrations.platforms.authorization import (
    AuthorizationCompletion,
    ProviderAuthorizationError,
)
from integrations.platforms.transport import HttpResponse
from integrations.platforms.youtube_authorization import YouTubeAuthorizationAdapter


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def adapter(responses):
    transport = RecordingTransport(responses)
    return YouTubeAuthorizationAdapter(
        transport=transport,
        client_id="fixture-youtube-client",
        client_secret="fixture-youtube-secret",
    ), transport


def test_youtube_exchanges_code_retains_refresh_and_discovers_channels() -> None:
    service, transport = adapter([
        HttpResponse(200, {
            "access_token": "fixture-youtube-access",
            "refresh_token": "fixture-youtube-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "https://www.googleapis.com/auth/youtube.upload",
        }, {}),
        HttpResponse(200, {"items": [
            {"id": "channel-1", "snippet": {"title": "Factory Channel"}},
        ]}, {}),
    ])

    bundle, accounts, capabilities = service.complete(AuthorizationCompletion(
        code="fixture-code",
        redirect_uri="https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback",
    ))

    assert bundle.primary.refresh_token == "fixture-youtube-refresh"
    assert bundle.primary.provider_scopes == (
        "https://www.googleapis.com/auth/youtube.upload",
    )
    assert [(item.channel, item.external_id, item.display_name) for item in accounts] == [
        ("YOUTUBE", "channel-1", "Factory Channel"),
    ]
    assert capabilities == ("PUBLISH", "METRICS_READ")
    assert set(bundle.candidate_tokens) == {accounts[0].candidate_id}
    assert transport.requests[1][1].startswith(
        "https://www.googleapis.com/youtube/v3/channels?"
    )


@pytest.mark.parametrize(
    "responses",
    [
        [HttpResponse(200, {"access_token": "fixture", "scope": "openid"}, {})],
        [
            HttpResponse(200, {
                "access_token": "fixture",
                "scope": "https://www.googleapis.com/auth/youtube.upload",
            }, {}),
            HttpResponse(200, {"items": []}, {}),
        ],
    ],
)
def test_youtube_rejects_missing_upload_scope_or_no_channel(responses) -> None:
    service, _ = adapter(responses)
    with pytest.raises(ProviderAuthorizationError) as error:
        service.complete(AuthorizationCompletion(
            code="fixture-code",
            redirect_uri="https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback",
        ))
    assert error.value.code == "INSUFFICIENT_CAPABILITY"


def test_youtube_provider_error_is_safe() -> None:
    service, _ = adapter([
        HttpResponse(500, {"error": {"message": "fixture-youtube-secret"}}, {}),
    ])
    with pytest.raises(ProviderAuthorizationError) as error:
        service.complete(AuthorizationCompletion(
            code="fixture-code",
            redirect_uri="https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback",
        ))
    assert error.value.code == "PROVIDER_UNAVAILABLE"
    assert "fixture-youtube-secret" not in str(error.value)
