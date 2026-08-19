from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import connection as db_connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

import pytest

from apps.identity.models import Organization, Role
from apps.platforms.models import (
    ConnectorCredential,
    Platform,
    ProviderConnection,
    ProviderConnectionEvent,
    SocialAccount,
    provider_event_writes,
)

from .buffer_test_utils import (
    authenticated_member,
    probe_fail,
    probe_ok,
)


API = "/api/v1/provider-connections/buffer"


def _connected_connection(organization, *, reference="vault://buffer/existing"):
    return ProviderConnection.objects.create(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference=reference,
        external_id="org-1",
        display_name="Acme Org",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )


@pytest.mark.django_db
def test_connect_success(admin_client, buffer_api):
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.probe_result = probe_ok()

    response = client.post(
        API,
        {"api_key": "sk-buffer-secret", "organization_id": "org-1"},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "BUFFER"
    assert body["configured"] is True
    assert body["connection_state"] == "CONNECTED"
    assert body["external_id"] == "org-1"
    assert "sk-buffer-secret" not in response.content.decode()
    assert "credential_reference" not in body


@pytest.mark.django_db
def test_connect_probe_failure_deletes_temp_token_and_creates_no_connection(
    admin_client, buffer_api,
):
    client, _user = admin_client
    token_store, connector = buffer_api
    connector.probe_result = probe_fail("BUFFER_AUTHENTICATION_REQUIRED")

    response = client.post(
        API,
        {"api_key": "sk-buffer-secret", "organization_id": "org-1"},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_AUTHENTICATION_REQUIRED"
    assert len(token_store.stored) == 1
    assert token_store.deleted == token_store.stored
    assert not ProviderConnection.objects.filter(
        provider=ProviderConnection.Provider.BUFFER,
    ).exists()


@pytest.mark.django_db
def test_connect_when_connected_returns_conflict(admin_client, buffer_api):
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.probe_result = probe_ok()
    first = client.post(API, {"api_key": "sk-1", "organization_id": "org-1"}, format="json")
    assert first.status_code == 201

    second = client.post(API, {"api_key": "sk-2", "organization_id": "org-1"}, format="json")

    assert second.status_code == 409
    assert second.json()["code"] == "BUFFER_ALREADY_CONNECTED"


@pytest.mark.django_db
def test_connect_reuses_primary_key_after_disconnect(admin_client, buffer_api):
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.probe_result = probe_ok()
    first = client.post(API, {"api_key": "sk-1", "organization_id": "org-1"}, format="json")
    connection_id = first.json()["id"]

    assert client.post(f"{API}/disconnect", {"confirm": True}, format="json").status_code == 200
    connector.probe_result = probe_ok()
    second = client.post(API, {"api_key": "sk-2", "organization_id": "org-1"}, format="json")

    assert second.status_code == 201
    assert second.json()["id"] == connection_id


@pytest.mark.django_db
def test_rotate_success_deletes_old_credential(admin_client, buffer_api):
    client, _user = admin_client
    token_store, connector = buffer_api
    connector.probe_result = probe_ok()
    client.post(API, {"api_key": "sk-old", "organization_id": "org-1"}, format="json")
    old_reference = token_store.stored[-1]

    response = client.patch(API, {"api_key": "sk-new"}, format="json")

    assert response.status_code == 200
    assert old_reference in token_store.deleted
    assert token_store.references == [token_store.stored[-1]]


@pytest.mark.django_db
def test_rotate_failure_deletes_new_and_keeps_old(admin_client, buffer_api):
    client, _user = admin_client
    token_store, connector = buffer_api
    connector.probe_result = probe_ok()
    client.post(API, {"api_key": "sk-old", "organization_id": "org-1"}, format="json")
    old_reference = token_store.stored[-1]
    connector.probe_result = probe_fail("BUFFER_AUTHENTICATION_REQUIRED")

    response = client.patch(API, {"api_key": "sk-new"}, format="json")

    assert response.status_code == 409
    assert old_reference in token_store.references
    connection = ProviderConnection.objects.get(provider=ProviderConnection.Provider.BUFFER)
    assert connection.credential_reference == old_reference


@pytest.mark.parametrize(
    ("code", "http_status", "expected_state"),
    [
        ("BUFFER_AUTHENTICATION_REQUIRED", 409, "REAUTHORIZATION_REQUIRED"),
        ("BUFFER_ORGANIZATION_NOT_FOUND", 400, "REAUTHORIZATION_REQUIRED"),
        ("BUFFER_CONFIGURATION_REQUIRED", 409, "CONFIGURATION_REQUIRED"),
        ("BUFFER_RATE_LIMITED", 429, "PROVIDER_UNAVAILABLE"),
        ("BUFFER_PROVIDER_UNAVAILABLE", 503, "PROVIDER_UNAVAILABLE"),
        ("BUFFER_CONTRACT_ERROR", 502, "PROVIDER_UNAVAILABLE"),
    ],
)
@pytest.mark.django_db
def test_probe_error_state_mapping(
    organization, admin_client, buffer_api, code, http_status, expected_state,
):
    _connection = _connected_connection(organization)
    client, _user = admin_client
    token_store, connector = buffer_api
    connector.probe_result = probe_fail(code)

    response = client.post(f"{API}/probe", {}, format="json")

    assert response.status_code == http_status
    assert response.data["code"] == code
    assert token_store.deleted == []
    _connection.refresh_from_db()
    assert _connection.connection_state == expected_state


@pytest.mark.django_db
def test_connect_rotate_probe_never_leak_token_or_reference(
    admin_client, buffer_api,
):
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.probe_result = probe_ok()

    connect = client.post(
        API, {"api_key": "sk-buffer-secret", "organization_id": "org-1"}, format="json",
    )
    rotate = client.patch(API, {"api_key": "sk-buffer-secret-2"}, format="json")
    probe = client.post(f"{API}/probe", {}, format="json")

    for response in (connect, rotate, probe):
        content = response.content.decode()
        assert "sk-buffer-secret" not in content
        assert "vault://buffer/fixture" not in content
        assert "credential_reference" not in response.json()


@pytest.mark.django_db
def test_non_admin_gets_403(organization, reader_client, buffer_api):
    _connection = _connected_connection(organization)
    client, _user = reader_client
    assert client.get(API).status_code == 403
    assert client.post(API, {"api_key": "sk", "organization_id": "org-1"}, format="json").status_code == 403
    assert client.patch(API, {"api_key": "sk"}, format="json").status_code == 403
    assert client.post(f"{API}/probe", {}, format="json").status_code == 403
    assert client.post(f"{API}/sync", {}, format="json").status_code == 403
    assert client.post(f"{API}/disconnect", {"confirm": True}, format="json").status_code == 403


@pytest.mark.django_db
def test_cross_organization_cannot_access(organization, admin_client, buffer_api):
    _connection = _connected_connection(organization)
    client, _user = admin_client
    other = Organization.objects.create(name="Other", slug="other-org")
    other_client, _ = authenticated_member(
        organization=other,
        role=Role.objects.create_administrator(),
        prefix="other-admin",
    )

    assert other_client.get(API).status_code == 404
    assert other_client.patch(API, {"api_key": "sk"}, format="json").status_code == 404
    assert other_client.post(f"{API}/probe", {}, format="json").status_code == 404
    assert other_client.post(f"{API}/sync", {}, format="json").status_code == 404
    assert other_client.post(f"{API}/disconnect", {"confirm": True}, format="json").status_code == 404


@pytest.mark.django_db
def test_disconnect_requires_confirmation(organization, admin_client, buffer_api):
    _connection = _connected_connection(organization)
    client, _user = admin_client
    response = client.post(f"{API}/disconnect", {"confirm": False}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_disconnect_deactivates_buffer_accounts(organization, admin_client, buffer_api):
    connection = _connected_connection(organization)
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="ch-1",
        external_id="li-page-1",
        display_name="Acme LinkedIn",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )
    client, _user = admin_client
    _token_store, _connector = buffer_api

    response = client.post(f"{API}/disconnect", {"confirm": True}, format="json")

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.status == SocialAccount.Status.INACTIVE
    assert account.connection_state == SocialAccount.ConnectionState.DISCONNECTED
    connection.refresh_from_db()
    assert connection.connection_state == ProviderConnection.ConnectionState.DISCONNECTED
    assert connection.credential_reference == ""


@pytest.mark.django_db
def test_disconnect_is_idempotent(organization, admin_client, buffer_api):
    _connection = _connected_connection(organization)
    client, _user = admin_client
    token_store, _connector = buffer_api

    first = client.post(f"{API}/disconnect", {"confirm": True}, format="json")
    second = client.post(f"{API}/disconnect", {"confirm": True}, format="json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert token_store.deleted.count("vault://buffer/existing") == 1


@pytest.mark.django_db
def test_provider_connection_events_are_append_only(organization):
    connection = _connected_connection(organization)
    with provider_event_writes():
        event = ProviderConnectionEvent.objects.create(
            organization=organization,
            provider_connection=connection,
            provider="BUFFER",
            actor=None,
            action=ProviderConnectionEvent.Action.PROBE,
            outcome=ProviderConnectionEvent.Outcome.SUCCESS,
        )

    with pytest.raises(ValidationError):
        event.delete()
    with pytest.raises(ValidationError):
        event.save()
    with pytest.raises(ValidationError):
        ProviderConnectionEvent.objects.filter(pk=event.pk).update(error_code="X")
    with pytest.raises(ValidationError):
        ProviderConnectionEvent.objects.bulk_update([event], ["error_code"])
    with pytest.raises(ValidationError):
        ProviderConnectionEvent.objects.filter(pk=event.pk).delete()


@pytest.mark.django_db
def test_provider_connection_event_rejects_sensitive_metadata(organization):
    connection = _connected_connection(organization)
    with pytest.raises(ValidationError):
        with provider_event_writes():
            ProviderConnectionEvent.objects.create(
                organization=organization,
                provider_connection=connection,
                provider="BUFFER",
                actor=None,
                action=ProviderConnectionEvent.Action.SYNC,
                outcome=ProviderConnectionEvent.Outcome.SUCCESS,
                metadata={"access_token": "secret"},
            )


@pytest.mark.django_db
def test_buffer_account_is_configured_but_has_no_publish_capability(
    organization, admin_client,
):
    connection = _connected_connection(organization)
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="ch-1",
        external_id="li-page-1",
        display_name="Acme LinkedIn",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )
    client, _user = admin_client

    response = client.get("/api/v1/social-accounts")

    account = response.json()["results"][0]
    assert account["credential_configured"] is True
    assert "PUBLISH" not in account["effective_capabilities"]
    assert "credential_reference" not in account


@pytest.mark.django_db
def test_direct_account_credential_configured_behavior_unchanged(
    organization, admin_client,
):
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=["PUBLISH"],
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="direct-page",
        display_name="Direct LinkedIn",
        publish_mode=SocialAccount.PublishMode.EXPORT_PACKAGE,
    )
    client, _user = admin_client

    response = client.get("/api/v1/social-accounts")

    account = response.json()["results"][0]
    assert account["credential_configured"] is True


class BufferProviderConnectionMigrationTest(TransactionTestCase):
    migrate_from = [
        ("platforms", "0010_remove_socialaccount_platforms_social_account_provider_shape_and_more"),
        ("identity", "0015_refresh_mission_permissions"),
    ]
    migrate_to = [("platforms", "0011_providerconnectionevent")]

    def test_migration_applies_forward_and_reverse_without_data_loss(self):
        executor = MigrationExecutor(db_connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        Organization = old_apps.get_model("identity", "Organization")
        ProviderConnection = old_apps.get_model("platforms", "ProviderConnection")
        organization = Organization.objects.create(name="Mig", slug="mig-org")
        ProviderConnection.objects.create(
            organization=organization,
            provider="BUFFER",
            credential_reference="vault://mig",
            external_id="org-1",
            connection_state="CONNECTED",
        )

        executor = MigrationExecutor(db_connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        assert "providerconnectionevent" in new_apps.all_models["platforms"]
        NewProviderConnection = new_apps.get_model("platforms", "ProviderConnection")
        assert NewProviderConnection.objects.count() == 1
        assert NewProviderConnection.objects.get().credential_reference == "vault://mig"

        executor = MigrationExecutor(db_connection)
        executor.migrate(self.migrate_from)
        back_apps = executor.loader.project_state(self.migrate_from).apps
        assert "providerconnectionevent" not in back_apps.all_models["platforms"]
