import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.ai.models import OrganizationAIProviderConfig
from apps.identity.models import Membership, Organization, Role
from integrations.ai.providers import DeepSeekAIProvider
from integrations.secrets import decrypt_secret


def member_client(organization, role, username):
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return client


@pytest.fixture
def provider_clients(db):
    own = Organization.objects.create(name="Provider Own", slug="provider-own")
    other = Organization.objects.create(name="Provider Other", slug="provider-other")
    admin_role = Role.objects.create_administrator()
    operator_role = Role.objects.create_operator()
    return {
        "own": own,
        "other": other,
        "admin": member_client(own, admin_role, "provider-admin"),
        "other_admin": member_client(other, admin_role, "provider-other-admin"),
        "operator": member_client(
            Organization.objects.create(name="Provider Operator", slug="provider-operator"),
            operator_role,
            "provider-operator",
        ),
    }


@pytest.mark.django_db
def test_admin_saves_encrypted_organization_config_without_key_echo(provider_clients):
    secret = "fixture-secret-key-never-return"
    response = provider_clients["admin"].put(
        "/api/v1/ai/provider-config",
        {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": secret,
            "enabled": True,
            "daily_budget_micros": 500_000,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "configured": True,
        "enabled": True,
        "daily_budget_micros": 500_000,
        "daily_spent_micros": 0,
        "daily_reserved_micros": 0,
        "price_table_version": "deepseek-usd-2026-08-18",
        "last_tested_at": None,
        "last_success_at": None,
        "last_error_code": "",
    }
    assert secret not in response.content.decode()
    config = OrganizationAIProviderConfig.objects.get(
        organization=provider_clients["own"]
    )
    assert config.encrypted_api_key != secret
    assert decrypt_secret(config.encrypted_api_key) == secret

    get_data = provider_clients["admin"].get("/api/v1/ai/provider-config").json()
    assert get_data == response.json()
    assert "api_key" not in get_data


@pytest.mark.django_db
def test_provider_config_is_admin_only_and_organization_scoped(provider_clients):
    forbidden = provider_clients["operator"].put(
        "/api/v1/ai/provider-config",
        {"provider": "deepseek", "model": "deepseek-chat", "api_key": "nope", "enabled": True},
        format="json",
    )
    assert forbidden.status_code == 403

    own = provider_clients["admin"].put(
        "/api/v1/ai/provider-config",
        {"provider": "deepseek", "model": "deepseek-chat", "api_key": "own-secret", "enabled": True},
        format="json",
    )
    assert own.status_code == 200

    foreign = provider_clients["other_admin"].get("/api/v1/ai/provider-config")
    assert foreign.status_code == 200
    assert foreign.json()["configured"] is False
    assert foreign.json()["enabled"] is False


@pytest.mark.django_db
def test_invalid_model_fails_closed_and_delete_clears_ciphertext(provider_clients):
    secret = "invalid-model-secret"
    invalid = provider_clients["admin"].put(
        "/api/v1/ai/provider-config",
        {"provider": "deepseek", "model": "not-allowed", "api_key": secret, "enabled": True},
        format="json",
    )
    assert invalid.status_code == 400
    assert secret not in invalid.content.decode()

    saved = provider_clients["admin"].put(
        "/api/v1/ai/provider-config",
        {"provider": "deepseek", "model": "deepseek-reasoner", "api_key": "saved-secret", "enabled": True},
        format="json",
    )
    assert saved.status_code == 200
    deleted = provider_clients["admin"].delete("/api/v1/ai/provider-config")
    assert deleted.status_code == 204
    config = OrganizationAIProviderConfig.objects.get(organization=provider_clients["own"])
    assert config.encrypted_api_key == ""
    assert config.enabled is False


@pytest.mark.django_db
def test_connection_test_records_only_safe_metadata(provider_clients, monkeypatch):
    secret = "connection-secret-never-return"
    saved = provider_clients["admin"].put(
        "/api/v1/ai/provider-config",
        {"provider": "deepseek", "model": "deepseek-chat", "api_key": secret, "enabled": True},
        format="json",
    )
    assert saved.status_code == 200
    monkeypatch.setattr(
        DeepSeekAIProvider,
        "test_connection",
        lambda self: {"ok": True, "latency_ms": 12},
    )

    response = provider_clients["admin"].post("/api/v1/ai/provider-config/test", {}, format="json")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["latency_ms"] == 12
    assert secret not in response.content.decode()
    config = OrganizationAIProviderConfig.objects.get(organization=provider_clients["own"])
    assert config.last_tested_at is not None
    assert config.last_success_at is not None
    assert config.last_error_code == ""

