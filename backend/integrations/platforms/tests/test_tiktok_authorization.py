from integrations.platforms.authorization import AuthorizationCompletion
from integrations.platforms.tiktok_authorization import TikTokAuthorizationAdapter
from integrations.platforms.transport import HttpResponse


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def test_unaudited_tiktok_creator_is_discovered_as_private_only() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {
            "access_token": "tiktok-token", "refresh_token": "tiktok-refresh",
            "open_id": "creator-open-id", "expires_in": 3600,
        }, {}),
        HttpResponse(200, {"data": {
            "creator_username": "acme_factory",
            "creator_nickname": "Acme Factory",
            "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
            "max_video_post_duration_sec": 300,
        }, "error": {"code": "ok", "message": "", "log_id": "fixture-log"}}, {}),
    ])
    adapter = TikTokAuthorizationAdapter(
        transport=transport,
        client_key="fixture-key",
        client_secret="fixture-secret",
        client_audited=False,
    )

    bundle, accounts, granted = adapter.complete(AuthorizationCompletion(
        code="fixture-tiktok-code",
        redirect_uri="https://local.invalid/tiktok/callback",
        pkce_reference="fixture-pkce-reference",
    ))

    assert [(item.channel, item.external_id, item.display_name, item.publication_mode) for item in accounts] == [
        ("TIKTOK", "creator-open-id", "Acme Factory", "PRIVATE_ONLY"),
    ]
    assert granted == ("PUBLISH",)
    assert bundle.primary.access_token == "tiktok-token"
    assert [url for _method, url, _kwargs in transport.requests] == [
        "https://open.tiktokapis.com/v2/oauth/token/",
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
    ]
    assert transport.requests[1][2]["headers"]["Authorization"] == "Bearer tiktok-token"

