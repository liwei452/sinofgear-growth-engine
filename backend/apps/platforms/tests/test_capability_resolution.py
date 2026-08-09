import pytest
from django.utils import timezone

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
        publish_mode=SocialAccount.PublishMode.API_AUTO,
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


@pytest.mark.django_db
def test_resolve_account_capabilities_fails_closed_for_malformed_legacy_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(name="Acme", slug="acme")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    PlatformCapability.objects.create(platform=platform, code=AccountCapability.PUBLISH)
    # Direct persistence models legacy data that predates validation.
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=[{"code": "PUBLISH"}],
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("publish_mode", "status", "expected"),
    [
        (SocialAccount.PublishMode.API_AUTO, SocialAccount.Status.ACTIVE, {AccountCapability.PUBLISH, AccountCapability.METRICS_READ}),
        (SocialAccount.PublishMode.MANUAL, SocialAccount.Status.ACTIVE, {AccountCapability.METRICS_READ}),
        (SocialAccount.PublishMode.EXPORT_PACKAGE, SocialAccount.Status.ACTIVE, {AccountCapability.METRICS_READ}),
        (SocialAccount.PublishMode.API_AUTO, SocialAccount.Status.INACTIVE, set()),
    ],
)
def test_resolve_account_capabilities_enforces_active_status_and_publish_mode(
    monkeypatch: pytest.MonkeyPatch, publish_mode: str, status: str,
    expected: set[AccountCapability],
) -> None:
    organization = Organization.objects.create(name="Acme", slug=f"acme-{publish_mode}-{status}")
    platform = Platform.objects.create(code=f"CHANNEL-{publish_mode}-{status}", name="Channel")
    PlatformCapability.objects.bulk_create([
        PlatformCapability(platform=platform, code=AccountCapability.PUBLISH),
        PlatformCapability(platform=platform, code=AccountCapability.METRICS_READ),
    ])
    credential = ConnectorCredential.objects.create(
        organization=organization, platform=platform, secret_reference="vault://safe",
        granted_scopes=[AccountCapability.PUBLISH, AccountCapability.METRICS_READ],
    )
    account = SocialAccount.objects.create(
        organization=organization, platform=platform, credential=credential,
        external_id="account", display_name="Account", publish_mode=publish_mode, status=status,
    )
    monkeypatch.setitem(CONNECTOR_CAPABILITIES, platform.code, {
        AccountCapability.PUBLISH, AccountCapability.METRICS_READ,
    })

    assert resolve_account_capabilities(account.id) == expected


@pytest.mark.django_db
def test_resolve_account_capabilities_rejects_expired_and_corrupt_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = Organization.objects.create(name="Acme", slug="acme-corrupt")
    foreign = Organization.objects.create(name="Foreign", slug="foreign-corrupt")
    platform = Platform.objects.create(code="CHANNEL-CORRUPT", name="Channel")
    other_platform = Platform.objects.create(code="OTHER-CORRUPT", name="Other")
    PlatformCapability.objects.create(platform=platform, code=AccountCapability.PUBLISH)
    credential = ConnectorCredential.objects.create(
        organization=organization, platform=platform, secret_reference="vault://safe",
        granted_scopes=[AccountCapability.PUBLISH], expires_at=timezone.now(),
    )
    account = SocialAccount.objects.create(
        organization=organization, platform=platform, credential=credential,
        external_id="account", display_name="Account", publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    monkeypatch.setitem(CONNECTOR_CAPABILITIES, platform.code, {AccountCapability.PUBLISH})

    assert resolve_account_capabilities(account.id) == set()
    ConnectorCredential.objects.filter(id=credential.id).update(expires_at=None, organization=foreign)
    assert resolve_account_capabilities(account.id) == set()
    ConnectorCredential.objects.filter(id=credential.id).update(organization=organization, platform=other_platform)
    assert resolve_account_capabilities(account.id) == set()
