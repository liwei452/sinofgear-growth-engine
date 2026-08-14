from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.connection_status import connection_summary
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


@pytest.mark.django_db
def test_connection_summary_distinguishes_missing_demo_ready_and_expired_accounts() -> None:
    organization = Organization.objects.create(name="Acme", slug="connection-acme")
    linkedin = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    facebook = Platform.objects.create(code="FACEBOOK", name="Facebook")
    instagram = Platform.objects.create(code="INSTAGRAM", name="Instagram")
    tiktok = Platform.objects.create(code="TIKTOK", name="TikTok")

    SocialAccount.objects.create(
        organization=organization,
        platform=facebook,
        external_id="demo-page",
        display_name="Demo Page",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "demo_fake"},
    )
    ready_credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=instagram,
        secret_reference="vault://instagram/acme",
        granted_scopes=["PUBLISH"],
        expires_at=timezone.now() + timedelta(hours=1),
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=instagram,
        credential=ready_credential,
        external_id="ig-acme",
        display_name="Acme Instagram",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )
    expired_credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=tiktok,
        secret_reference="vault://tiktok/acme",
        granted_scopes=["PUBLISH"],
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=tiktok,
        credential=expired_credential,
        external_id="tiktok-acme",
        display_name="Acme TikTok",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )

    assert connection_summary(
        organization=organization, platform_code=linkedin.code,
    ).status == "NOT_CONNECTED"
    assert connection_summary(
        organization=organization, platform_code=facebook.code,
    ).status == "CONNECTED"
    assert connection_summary(
        organization=organization, platform_code=instagram.code,
    ).status == "CONNECTED"
    expired = connection_summary(organization=organization, platform_code=tiktok.code)
    assert expired.status == "REAUTHORIZATION_REQUIRED"
    assert expired.recovery_action == "重新连接"


@pytest.mark.django_db
def test_official_connection_without_credential_fails_closed() -> None:
    organization = Organization.objects.create(name="Acme", slug="connection-no-token")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        external_id="linkedin-acme",
        display_name="Acme LinkedIn",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )

    summary = connection_summary(organization=organization, platform_code=platform.code)

    assert summary.status == "CONFIGURATION_REQUIRED"
    assert summary.recovery_action == "连接账号"
