from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.growth.models import GrowthPublishBatch
from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import AccountConnectionSession, Platform, SocialAccount
from apps.platforms.oauth import create_authorization_attempt
from integrations.platforms.authorization import (
    ManagedPublishingAccount,
    ProviderCredentialBundle,
)
from integrations.platforms.authorization_registry import AuthorizationAdapterRegistry
from integrations.platforms.token_store import OAuthTokenSet


def authenticated_client(*, organization: Organization, username: str):
    user = get_user_model().objects.create_user(username=username, password="safe-password")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_administrator(),
    )
    client = APIClient()
    assert client.login(username=username, password="safe-password")
    return client, user


class FixtureAuthorizationAdapter:
    def __init__(self, account: ManagedPublishingAccount):
        self.account = account

    def complete(self, request):
        token = OAuthTokenSet(
            access_token="fixture-provider-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        return (
            ProviderCredentialBundle(
                primary=token,
                candidate_tokens={self.account.candidate_id: token},
                issued_at=datetime.now(UTC),
            ),
            [self.account],
            ("PUBLISH",),
        )


class FixtureTokenStore:
    def __init__(self):
        self.deleted = []

    def store(self, bundle, context):
        assert "fixture-provider-token" not in repr(bundle)
        return "vault://fixture/bundle-1"

    def bind(self, reference, candidate_id):
        assert reference == "vault://fixture/bundle-1"
        return f"vault://fixture/account/{candidate_id}"

    def resolve(self, reference):
        raise AssertionError(f"Unexpected resolve: {reference}")

    def delete(self, reference):
        self.deleted.append(reference)


@pytest.fixture
def completion_context(monkeypatch):
    from apps.platforms import views as platform_views

    organization = Organization.objects.create(name="Acme", slug="completion-api-acme")
    platform = Platform.objects.create(code="FACEBOOK", name="Facebook")
    client, actor = authenticated_client(
        organization=organization, username="completion-admin",
    )
    account = ManagedPublishingAccount(
        candidate_id="eab6c52d-af6a-5e8d-b884-c7aa87c45bb8",
        external_id="page-123",
        display_name="Acme Page",
        channel="FACEBOOK",
        capabilities=("PUBLISH",),
        publication_mode="PUBLIC",
        discovered_at=datetime.now(UTC),
    )
    token_store = FixtureTokenStore()
    monkeypatch.setattr(
        platform_views,
        "authorization_registry",
        AuthorizationAdapterRegistry({"META": FixtureAuthorizationAdapter(account)}),
        raising=False,
    )
    monkeypatch.setattr(
        platform_views, "connection_token_store", token_store, raising=False,
    )
    return organization, platform, client, actor, account, token_store


@pytest.mark.django_db
@override_settings(SOCIAL_PROVIDER_CONFIG={
    "META": {
        "enabled": True,
        "redirect_uri": "https://growth.example.com/api/v1/platform-connections/FACEBOOK/callback",
    },
})
def test_callback_creates_safe_selection_session_then_explicit_confirmation_connects_without_publishing(
    completion_context,
) -> None:
    organization, platform, client, actor, account, _token_store = completion_context
    started = create_authorization_attempt(
        organization=organization,
        actor=actor,
        platform=platform,
        return_path="/promotion?source=account-connect",
    )

    callback = client.get(
        "/api/v1/platform-connections/FACEBOOK/callback",
        {"code": "fixture-authorization-code", "state": started.raw_state},
    )

    assert callback.status_code == 302
    parsed = urlsplit(callback.headers["Location"])
    query = parse_qs(parsed.query)
    assert parsed.path == "/promotion"
    assert query["source"] == ["account-connect"]
    assert query["connection_status"] == ["ready"]
    session_id = query["connection_session"][0]
    assert "code" not in query
    assert "state" not in query
    assert "token" not in callback.headers["Location"].lower()
    assert SocialAccount.objects.count() == 0
    assert GrowthPublishBatch.objects.count() == 0

    summary = client.get(f"/api/v1/platform-connection-sessions/{session_id}")
    assert summary.status_code == 200
    assert summary.json() == {
        "id": session_id,
        "platform": "FACEBOOK",
        "platform_name": "Facebook",
        "expires_at": summary.json()["expires_at"],
        "candidates": [{
            "candidate_id": account.candidate_id,
            "display_name": "Acme Page",
            "channel": "FACEBOOK",
            "capability_label": "可发布",
            "publication_mode": "PUBLIC",
        }],
    }
    serialized = str(summary.json()).lower()
    for forbidden in ("token", "secret", "scope", "credential", "external_id"):
        assert forbidden not in serialized

    unknown = client.post(
        f"/api/v1/platform-connection-sessions/{session_id}/confirm",
        {"candidate_id": account.candidate_id, "access_token": "must-be-rejected"},
        format="json",
    )
    confirmed = client.post(
        f"/api/v1/platform-connection-sessions/{session_id}/confirm",
        {"candidate_id": account.candidate_id},
        format="json",
    )

    assert unknown.status_code == 400
    assert confirmed.status_code == 200
    assert confirmed.json() == {
        "platform": "FACEBOOK",
        "status": "CONNECTED",
        "connection_label": "已连接",
        "recovery_action": "",
        "mode": "OFFICIAL",
    }
    assert GrowthPublishBatch.objects.count() == 0
    connected = SocialAccount.objects.get()
    assert connected.external_id == "page-123"
    assert connected.credential.secret_reference == f"vault://fixture/account/{account.candidate_id}"

    replay = client.post(
        f"/api/v1/platform-connection-sessions/{session_id}/confirm",
        {"candidate_id": account.candidate_id},
        format="json",
    )
    assert replay.status_code == 200
    assert SocialAccount.objects.count() == 1


@pytest.mark.django_db
@override_settings(SOCIAL_PROVIDER_CONFIG={
    "META": {
        "enabled": True,
        "redirect_uri": "https://growth.example.com/api/v1/platform-connections/FACEBOOK/callback",
    },
})
def test_callback_state_and_selection_session_are_actor_and_tenant_bound(completion_context) -> None:
    organization, platform, client, actor, _account, _token_store = completion_context
    other_organization = Organization.objects.create(name="Other", slug="completion-api-other")
    other_client, _other_actor = authenticated_client(
        organization=other_organization, username="completion-other-admin",
    )
    started = create_authorization_attempt(
        organization=organization, actor=actor, platform=platform, return_path="/promotion",
    )

    wrong_actor = other_client.get(
        "/api/v1/platform-connections/FACEBOOK/callback",
        {"code": "fixture-code", "state": started.raw_state},
    )
    assert wrong_actor.status_code == 400
    assert AccountConnectionSession.objects.count() == 0

    callback = client.get(
        "/api/v1/platform-connections/FACEBOOK/callback",
        {"code": "fixture-code", "state": started.raw_state},
    )
    session_id = parse_qs(urlsplit(callback.headers["Location"]).query)["connection_session"][0]
    assert other_client.get(f"/api/v1/platform-connection-sessions/{session_id}").status_code == 404
    assert other_client.post(
        f"/api/v1/platform-connection-sessions/{session_id}/confirm",
        {"candidate_id": "eab6c52d-af6a-5e8d-b884-c7aa87c45bb8"},
        format="json",
    ).status_code == 404
