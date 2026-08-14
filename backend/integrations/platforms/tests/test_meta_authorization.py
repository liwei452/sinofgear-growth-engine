from datetime import timedelta

import pytest

from integrations.platforms.authorization import (
    AuthorizationCompletion,
    ProviderAuthorizationError,
)
from integrations.platforms.meta_authorization import MetaAuthorizationAdapter
from integrations.platforms.transport import HttpResponse


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def completion() -> AuthorizationCompletion:
    return AuthorizationCompletion(
        code="fixture-meta-code",
        redirect_uri="https://local.invalid/meta/callback",
        pkce_reference="",
    )


def test_meta_discovers_separate_publishable_page_and_instagram_candidates() -> None:
    transport = RecordingTransport([
        HttpResponse(200, {"access_token": "user-token", "expires_in": 3600}, {}),
        HttpResponse(200, {"data": [
            {
                "id": "page-123", "name": "Acme Page", "access_token": "page-token",
                "tasks": ["CREATE_CONTENT", "ANALYZE"],
                "instagram_business_account": {"id": "ig-456", "name": "Acme Instagram"},
            },
            {"id": "page-readonly", "name": "Read only", "tasks": ["MODERATE"]},
        ]}, {}),
    ])
    adapter = MetaAuthorizationAdapter(
        transport=transport,
        client_id="fixture-client",
        client_secret="fixture-secret",
        graph_base_url="https://graph.facebook.com/v23.0",
    )

    bundle, accounts, granted = adapter.complete(completion())

    assert {(item.channel, item.external_id, item.display_name) for item in accounts} == {
        ("FACEBOOK", "page-123", "Acme Page"),
        ("INSTAGRAM", "ig-456", "Acme Instagram"),
    }
    assert all(item.publication_mode == "PUBLIC" for item in accounts)
    assert granted == ("PUBLISH", "METRICS_READ")
    assert bundle.primary.access_token == "user-token"
    assert bundle.primary.expires_at is not None
    assert timedelta(minutes=59) < bundle.primary.expires_at - bundle.issued_at <= timedelta(hours=1)
    assert {item.candidate_id for item in accounts} == set(bundle.candidate_tokens)
    assert {token.access_token for token in bundle.candidate_tokens.values()} == {"page-token"}
    assert [(method, url) for method, url, _kwargs in transport.requests] == [
        ("POST", "https://graph.facebook.com/v23.0/oauth/access_token"),
        ("GET", "https://graph.facebook.com/v23.0/me/accounts?fields=id,name,access_token,tasks,instagram_business_account{id,name}"),
    ]


def test_meta_authorization_failure_is_normalized_without_provider_or_secret_text() -> None:
    transport = RecordingTransport([
        HttpResponse(400, {"error": {"message": "fixture-meta-code fixture-secret rejected"}}, {}),
    ])
    adapter = MetaAuthorizationAdapter(
        transport=transport,
        client_id="fixture-client",
        client_secret="fixture-secret",
    )

    with pytest.raises(ProviderAuthorizationError) as captured:
        adapter.complete(completion())

    assert captured.value.code == "AUTHORIZATION_REJECTED"
    assert "fixture-meta-code" not in str(captured.value)
    assert "fixture-secret" not in str(captured.value)

