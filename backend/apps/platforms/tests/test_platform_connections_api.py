from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import OAuthConnectionAttempt, Platform


def client_for(*, organization: Organization, role: Role, username: str) -> APIClient:
    user = get_user_model().objects.create_user(username=username, password="safe-password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="safe-password")
    return client


@pytest.fixture
def connection_api_context():
    organization = Organization.objects.create(name="Acme", slug="connection-api-acme")
    platforms = {
        code: Platform.objects.create(code=code, name=name)
        for code, name in [
            ("LINKEDIN", "LinkedIn"), ("FACEBOOK", "Facebook"),
            ("INSTAGRAM", "Instagram"), ("TIKTOK", "TikTok"),
        ]
    }
    roles = {
        "admin": Role.objects.create_administrator(),
        "reader": Role.objects.create_reviewer(),
    }
    return organization, platforms, roles


@pytest.mark.django_db
def test_publishing_reader_lists_only_safe_connection_summaries(connection_api_context) -> None:
    organization, _platforms, roles = connection_api_context
    client = client_for(
        organization=organization, role=roles["reader"], username="connection-reader",
    )

    response = client.get("/api/v1/platform-connections")

    assert response.status_code == 200
    assert response.json() == {"results": [{
        "platform": code, "platform_name": name, "status": "NOT_CONNECTED",
        "connection_label": "未连接", "recovery_action": "连接账号", "mode": "",
        "account_id": "", "publication_mode": "UNAVAILABLE",
    } for code, name in [
        ("LINKEDIN", "LinkedIn"), ("FACEBOOK", "Facebook"),
        ("INSTAGRAM", "Instagram"), ("TIKTOK", "TikTok"), ("YOUTUBE", "YouTube"),
    ]]}
    serialized = str(response.json()).lower()
    assert "token" not in serialized
    assert "secret" not in serialized
    assert "credential" not in serialized
    assert "scope" not in serialized


@pytest.mark.django_db
def test_only_credential_manager_can_start_authorization_and_disabled_is_fail_closed(
    connection_api_context,
) -> None:
    organization, _platforms, roles = connection_api_context
    reader = client_for(
        organization=organization, role=roles["reader"], username="authorize-reader",
    )
    admin = client_for(
        organization=organization, role=roles["admin"], username="authorize-admin",
    )

    assert reader.post(
        "/api/v1/platform-connections/LINKEDIN/authorize",
        {"return_path": "/promotion"}, format="json",
    ).status_code == 403
    response = admin.post(
        "/api/v1/platform-connections/LINKEDIN/authorize",
        {"return_path": "/promotion"}, format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFIGURATION_REQUIRED"
    assert OAuthConnectionAttempt.objects.count() == 0


@pytest.mark.django_db
@override_settings(SOCIAL_PROVIDER_CONFIG={
    "LINKEDIN": {
        "enabled": True,
        "client_id": "fixture-client-id",
        "authorization_url": "https://www.linkedin.com/oauth/v2/authorization",
        "redirect_uri": "https://growth.example.com/api/v1/platform-connections/LINKEDIN/callback",
    }
})
def test_enabled_provider_returns_one_time_official_authorization_url(connection_api_context) -> None:
    organization, _platforms, roles = connection_api_context
    admin = client_for(
        organization=organization, role=roles["admin"], username="enabled-authorize-admin",
    )

    unknown = admin.post(
        "/api/v1/platform-connections/LINKEDIN/authorize",
        {"return_path": "/promotion", "client_secret": "must-not-be-accepted"},
        format="json",
    )
    response = admin.post(
        "/api/v1/platform-connections/LINKEDIN/authorize",
        {"return_path": "/promotion"}, format="json",
    )

    assert unknown.status_code == 400
    assert response.status_code == 201
    assert response.json()["status"] == "AUTHORIZATION_REQUIRED"
    parsed = urlsplit(response.json()["authorization_url"])
    query = parse_qs(parsed.query)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https", "www.linkedin.com", "/oauth/v2/authorization",
    )
    assert query["client_id"] == ["fixture-client-id"]
    assert query["redirect_uri"] == ["https://growth.example.com/api/v1/platform-connections/LINKEDIN/callback"]
    assert len(query["state"][0]) >= 32
    attempt = OAuthConnectionAttempt.objects.get()
    assert query["state"][0] not in attempt.state_hash
    serialized = str(response.json()).lower()
    assert "client_secret" not in serialized
    assert "access_token" not in serialized


@pytest.mark.django_db
def test_authorization_rejects_unknown_platform_and_external_return_path(connection_api_context) -> None:
    organization, _platforms, roles = connection_api_context
    admin = client_for(
        organization=organization, role=roles["admin"], username="invalid-authorize-admin",
    )

    assert admin.post(
        "/api/v1/platform-connections/UNKNOWN/authorize",
        {"return_path": "/promotion"}, format="json",
    ).status_code == 404
    assert admin.post(
        "/api/v1/platform-connections/LINKEDIN/authorize",
        {"return_path": "https://evil.example/steal"}, format="json",
    ).status_code == 400
