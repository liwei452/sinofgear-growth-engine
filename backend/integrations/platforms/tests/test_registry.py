import pytest

from apps.identity.models import Organization
from apps.platforms.models import Platform, ProviderConnection, SocialAccount
from integrations.platforms.manual_fake import ManualPackageFakeConnector
from integrations.platforms.registry import ConnectorConfigurationRequired, ConnectorRegistry


class OfficialConnector:
    pass


@pytest.mark.django_db
def test_registry_allows_fake_only_for_explicit_demo_accounts() -> None:
    organization = Organization.objects.create(name="Acme", slug="registry-demo")
    platform = Platform.objects.create(code="FACEBOOK", name="Facebook")
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        external_id="demo-page",
        display_name="Demo Page",
        connector_metadata={"connection_kind": "demo_fake"},
    )

    connector = ConnectorRegistry().resolve(account)

    assert isinstance(connector, ManualPackageFakeConnector)


@pytest.mark.django_db
def test_registry_resolves_configured_official_connector_without_fake_fallback() -> None:
    organization = Organization.objects.create(name="Acme", slug="registry-official")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        external_id="acme",
        display_name="Acme LinkedIn",
        connector_metadata={"connection_kind": "official_oauth"},
    )
    official = OfficialConnector()

    assert ConnectorRegistry(official_connectors={"LINKEDIN": official}).resolve(account) is official

    with pytest.raises(ConnectorConfigurationRequired):
        ConnectorRegistry().resolve(account)


@pytest.mark.django_db
def test_registry_rejects_unclassified_accounts() -> None:
    organization = Organization.objects.create(name="Acme", slug="registry-unknown")
    platform = Platform.objects.create(code="TIKTOK", name="TikTok")
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        external_id="acme",
        display_name="Acme TikTok",
    )

    with pytest.raises(ConnectorConfigurationRequired):
        ConnectorRegistry().resolve(account)


@pytest.mark.django_db
def test_registry_routes_buffer_by_provider_before_direct_platform_code() -> None:
    organization = Organization.objects.create(name="Acme", slug="registry-buffer")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    connection = ProviderConnection.objects.create(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer/acme",
        external_id="org-1",
        display_name="Acme Buffer",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-1",
        external_id="linkedin-page-1",
        display_name="Acme LinkedIn",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connection_state=SocialAccount.ConnectionState.CONNECTED,
        connector_metadata={
            "fixture": "phase-a-e2e",
            "connection_kind": "demo_fake",
        },
    )
    direct = OfficialConnector()
    buffer = OfficialConnector()
    registry = ConnectorRegistry(
        official_connectors={"LINKEDIN": direct},
        provider_connectors={"BUFFER": buffer},
    )

    assert registry.resolve(account) is buffer
