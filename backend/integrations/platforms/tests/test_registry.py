import pytest

from apps.identity.models import Organization
from apps.platforms.models import Platform, SocialAccount
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
