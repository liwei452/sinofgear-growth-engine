from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.identity.models import Organization, Role
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount
from apps.platforms.tests.test_social_accounts_api import create_member


def make_account(organization, *, suffix):
    platform = Platform.objects.create(code=f"LINKEDIN-{suffix}", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference=f"vault://fixture/{suffix}",
        granted_scopes=["PUBLISH"],
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id=f"company-{suffix}",
        display_name="Factory",
        publish_mode=SocialAccount.PublishMode.API_CONFIRM,
        connector_metadata={"connection_kind": "official_oauth"},
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )


@pytest.mark.django_db
def test_lifecycle_actions_require_manager_tenant_and_disconnect_confirmation(monkeypatch) -> None:
    own = Organization.objects.create(name="Own", slug=f"own-{uuid4()}")
    other = Organization.objects.create(name="Other", slug=f"other-{uuid4()}")
    admin = Role.objects.create_administrator()
    reader = Role.objects.create_reviewer()
    account = make_account(own, suffix="own")
    foreign = make_account(other, suffix="other")
    admin_client = create_member(organization=own, role=admin, username=f"admin-{uuid4()}")
    reader_client = create_member(organization=own, role=reader, username=f"reader-{uuid4()}")

    assert reader_client.post(f"/api/v1/social-accounts/{account.id}/probe", {}).status_code == 403
    assert admin_client.post(f"/api/v1/social-accounts/{foreign.id}/probe", {}).status_code == 404
    rejected = admin_client.post(
        f"/api/v1/social-accounts/{account.id}/disconnect",
        {"confirm": False},
        format="json",
    )
    assert rejected.status_code == 400
    account.refresh_from_db()
    assert account.connection_state == SocialAccount.ConnectionState.CONNECTED
