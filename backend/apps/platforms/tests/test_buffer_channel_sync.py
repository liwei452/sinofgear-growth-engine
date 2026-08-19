from __future__ import annotations

import pytest

from apps.platforms.models import (
    Platform,
    ProviderConnection,
    SocialAccount,
)

from .buffer_test_utils import (
    channel,
    connected_connection,
    discover_fail,
    discover_ok,
    ignored_channel,
)


API = "/api/v1/provider-connections/buffer"


def _platforms():
    return [
        Platform.objects.create(code="LINKEDIN", name="LinkedIn"),
        Platform.objects.create(code="FACEBOOK", name="Facebook"),
        Platform.objects.create(code="INSTAGRAM", name="Instagram"),
    ]


@pytest.mark.django_db
def test_sync_creates_three_channels_first_time(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
        channel(platform_code="FACEBOOK", provider_account_id="fb-1", external_id="fb-page"),
        channel(platform_code="INSTAGRAM", provider_account_id="ig-1", external_id="ig-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["created_count"] == 3
    assert body["updated_count"] == 0
    assert SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).count() == 3


@pytest.mark.django_db
def test_sync_is_idempotent(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    first = client.post(f"{API}/sync", {}, format="json")
    second = client.post(f"{API}/sync", {}, format="json")

    assert first.json()["created_count"] == 1
    assert second.json()["created_count"] == 0
    assert second.json()["updated_count"] == 1
    assert SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).count() == 1


@pytest.mark.django_db
def test_sync_updates_name_and_metadata(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])
    client.post(f"{API}/sync", {}, format="json")
    connector.discover_result = discover_ok([
        channel(
            platform_code="LINKEDIN",
            provider_account_id="li-1",
            external_id="li-page",
            display_name="Renamed Page",
            avatar="https://cdn.example.com/new.png",
        ),
    ])

    client.post(f"{API}/sync", {}, format="json")

    account = SocialAccount.objects.get(provider=SocialAccount.Provider.BUFFER)
    assert account.display_name == "Renamed Page"
    assert account.connector_metadata["avatar"] == "https://cdn.example.com/new.png"
    assert account.connector_metadata["connection_kind"] == "buffer"


@pytest.mark.django_db
def test_sync_marks_disappeared_channel_inactive(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
        channel(platform_code="FACEBOOK", provider_account_id="fb-1", external_id="fb-page"),
    ])
    client.post(f"{API}/sync", {}, format="json")
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    result = client.post(f"{API}/sync", {}, format="json")

    assert result.json()["disconnected_count"] == 1
    disappeared = SocialAccount.objects.get(provider_account_id="fb-1")
    assert disappeared.status == SocialAccount.Status.INACTIVE
    assert disappeared.connection_state == SocialAccount.ConnectionState.DISCONNECTED


@pytest.mark.django_db
def test_sync_reactivates_reappearing_channel(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
        channel(platform_code="FACEBOOK", provider_account_id="fb-1", external_id="fb-page"),
    ])
    client.post(f"{API}/sync", {}, format="json")
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])
    client.post(f"{API}/sync", {}, format="json")
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
        channel(platform_code="FACEBOOK", provider_account_id="fb-1", external_id="fb-page"),
    ])

    client.post(f"{API}/sync", {}, format="json")

    account = SocialAccount.objects.get(provider_account_id="fb-1")
    assert account.status == SocialAccount.Status.ACTIVE
    assert account.connection_state == SocialAccount.ConnectionState.CONNECTED


@pytest.mark.django_db
def test_direct_external_id_conflict_rolls_back(organization, admin_client, buffer_api):
    connected_connection(organization)
    linkedin = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    SocialAccount.objects.create(
        organization=organization,
        platform=linkedin,
        provider=SocialAccount.Provider.DIRECT,
        external_id="li-page",
        display_name="Direct LinkedIn",
    )
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_CHANNEL_MAPPING_CONFLICT"
    assert not SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).exists()


@pytest.mark.django_db
def test_provider_account_id_platform_drift_rolls_back(organization, admin_client, buffer_api):
    connection = connected_connection(organization)
    Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    facebook = Platform.objects.create(code="FACEBOOK", name="Facebook")
    SocialAccount.objects.create(
        organization=organization,
        platform=facebook,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="li-1",
        external_id="li-page",
        display_name="Drifted",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_CHANNEL_MAPPING_CONFLICT"


@pytest.mark.django_db
def test_missing_platform_rolls_back(organization, admin_client, buffer_api):
    connected_connection(organization)
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_CHANNEL_MAPPING_CONFLICT"
    assert not SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).exists()


@pytest.mark.django_db
def test_credential_rotated_during_network_returns_changed(organization, admin_client, buffer_api):
    connection = connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api

    def rotate_during_discover(_request):
        ProviderConnection.objects.filter(pk=connection.pk).update(
            credential_reference="vault://buffer/rotated",
        )

    connector.on_discover = rotate_during_discover
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_CONNECTION_CHANGED"
    assert not SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).exists()


@pytest.mark.django_db
def test_connection_disconnected_during_network_no_writes(organization, admin_client, buffer_api):
    connection = connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api

    def disconnect_during_discover(_request):
        ProviderConnection.objects.filter(pk=connection.pk).update(
            connection_state=ProviderConnection.ConnectionState.DISCONNECTED,
            credential_reference="",
        )

    connector.on_discover = disconnect_during_discover
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "BUFFER_CONNECTION_CHANGED"
    assert not SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).exists()


@pytest.mark.django_db
def test_channel_state_mapping(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
        channel(platform_code="FACEBOOK", provider_account_id="fb-1", external_id="fb-page", is_disconnected=True),
        channel(platform_code="INSTAGRAM", provider_account_id="ig-1", external_id="ig-page", is_locked=True),
    ])

    client.post(f"{API}/sync", {}, format="json")

    healthy = SocialAccount.objects.get(provider_account_id="li-1")
    disconnected = SocialAccount.objects.get(provider_account_id="fb-1")
    locked = SocialAccount.objects.get(provider_account_id="ig-1")
    assert healthy.connection_state == SocialAccount.ConnectionState.CONNECTED
    assert disconnected.connection_state == SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
    assert disconnected.reauthorization_required_at is not None
    assert locked.connection_state == SocialAccount.ConnectionState.INSUFFICIENT_CAPABILITY
    assert locked.lifecycle_error_code == "BUFFER_CHANNEL_LOCKED"


@pytest.mark.django_db
def test_queue_paused_channel_stays_connected(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page", is_queue_paused=True),
    ])

    client.post(f"{API}/sync", {}, format="json")

    account = SocialAccount.objects.get(provider_account_id="li-1")
    assert account.connection_state == SocialAccount.ConnectionState.CONNECTED
    assert account.connector_metadata["is_queue_paused"] is True


@pytest.mark.django_db
def test_unsupported_channels_are_only_ignored(organization, admin_client, buffer_api):
    connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_ok(
        channels=[channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page")],
        ignored=[ignored_channel("tw-1", "twitter")],
    )

    response = client.post(f"{API}/sync", {}, format="json")

    assert response.status_code == 200
    assert response.json()["ignored_channels"] == [
        {"provider_account_id": "tw-1", "service": "twitter", "reason": "该平台暂不支持通过 Buffer 同步。"},
    ]
    assert SocialAccount.objects.filter(provider=SocialAccount.Provider.BUFFER).count() == 1


@pytest.mark.django_db
def test_last_sync_at_only_updates_after_full_success(organization, admin_client, buffer_api):
    connection = connected_connection(organization)
    _platforms()
    client, _user = admin_client
    _token_store, connector = buffer_api
    connector.discover_result = discover_fail("BUFFER_PROVIDER_UNAVAILABLE")

    failed = client.post(f"{API}/sync", {}, format="json")
    connection.refresh_from_db()
    assert failed.status_code == 503
    assert connection.last_sync_at is None

    connector.discover_result = discover_ok([
        channel(platform_code="LINKEDIN", provider_account_id="li-1", external_id="li-page"),
    ])
    success = client.post(f"{API}/sync", {}, format="json")
    connection.refresh_from_db()
    assert success.status_code == 200
    assert connection.last_sync_at is not None
