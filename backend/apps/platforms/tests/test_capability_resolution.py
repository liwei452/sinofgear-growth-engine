import pytest

from apps.identity.models import Organization
from apps.platforms.capabilities import AccountCapability, CONNECTOR_CAPABILITIES, resolve_account_capabilities
from apps.platforms.models import ConnectorCredential, Platform, PlatformCapability, SocialAccount


@pytest.mark.django_db
def test_resolve_account_capabilities_intersects_platform_connector_and_granted_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing any one capability source must remove it from the effective set."""
    organization = Organization.objects.create(name="Acme", slug="acme")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    PlatformCapability.objects.bulk_create(
        [
            PlatformCapability(platform=platform, code=AccountCapability.PUBLISH),
            PlatformCapability(platform=platform, code=AccountCapability.METRICS_READ),
        ]
    )
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=[AccountCapability.PUBLISH, AccountCapability.COMMENT_READ],
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="acme-linkedin",
        display_name="Acme LinkedIn",
    )

    monkeypatch.setitem(CONNECTOR_CAPABILITIES, "LINKEDIN", {AccountCapability.PUBLISH, AccountCapability.METRICS_READ})

    assert resolve_account_capabilities(account.id) == {AccountCapability.PUBLISH}


@pytest.mark.django_db
def test_resolve_account_capabilities_is_empty_without_registered_connector() -> None:
    organization = Organization.objects.create(name="Acme", slug="acme")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    PlatformCapability.objects.create(platform=platform, code=AccountCapability.PUBLISH)
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=[AccountCapability.PUBLISH],
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="acme-linkedin",
        display_name="Acme LinkedIn",
    )

    assert resolve_account_capabilities(account.id) == set()


@pytest.mark.django_db
def test_resolve_account_capabilities_requires_each_intersection_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(name="Acme", slug="acme")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=[AccountCapability.PUBLISH],
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="acme-linkedin",
        display_name="Acme LinkedIn",
    )
    monkeypatch.setitem(CONNECTOR_CAPABILITIES, "LINKEDIN", {AccountCapability.PUBLISH})

    assert resolve_account_capabilities(account.id) == set()
