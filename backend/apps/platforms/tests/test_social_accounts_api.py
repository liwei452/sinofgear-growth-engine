import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import (
    ConnectorCredential, Platform, PlatformCapability, ProviderConnection, SocialAccount,
)
from apps.platforms.capabilities import CONNECTOR_CAPABILITIES
from apps.platforms.codes import AccountCapability


def create_member(*, organization: Organization, role: Role, username: str) -> APIClient:
    user = get_user_model().objects.create_user(username=username, password="correct-horse-battery-staple")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="correct-horse-battery-staple")
    return client


@pytest.fixture
def platform() -> Platform:
    return Platform.objects.create(code="LINKEDIN", name="LinkedIn")


@pytest.fixture
def organizations() -> tuple[Organization, Organization]:
    return (
        Organization.objects.create(name="Own organization", slug="own-organization"),
        Organization.objects.create(name="Other organization", slug="other-organization"),
    )


@pytest.fixture
def roles() -> dict[str, Role]:
    return {
        role.code: role
        for role in (Role.objects.create_administrator(), Role.objects.create_reviewer())
    }


@pytest.mark.django_db
def test_authenticated_member_can_list_platform_definitions(platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]) -> None:
    client = create_member(organization=organizations[0], role=roles[Role.Code.REVIEWER], username="reviewer")

    response = client.get("/api/v1/platforms")

    assert response.status_code == 200
    assert response.json()["results"] == [{
        "id": str(platform.id), "code": "LINKEDIN", "name": "LinkedIn", "capabilities": [],
    }]


@pytest.mark.django_db
def test_platform_listing_uses_prefetched_capabilities_in_two_queries(
    django_assert_num_queries: pytest.FixtureRequest, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    first = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    second = Platform.objects.create(code="YOUTUBE", name="YouTube")
    PlatformCapability.objects.bulk_create(
        [PlatformCapability(platform=first, code="PUBLISH"), PlatformCapability(platform=second, code="METRICS_READ")]
    )
    client = create_member(organization=organizations[0], role=roles[Role.Code.REVIEWER], username="reviewer")

    # Session and membership authentication use three queries; the platform
    # list itself must use one query plus one prefetched-capability query.
    with django_assert_num_queries(7):
        response = client.get("/api/v1/platforms")

    assert response.status_code == 200


@pytest.mark.django_db
def test_anonymous_user_cannot_list_platforms() -> None:
    assert APIClient().get("/api/v1/platforms").status_code == 403
    assert APIClient().get("/api/v1/social-accounts").status_code == 403


@pytest.mark.django_db
def test_administrator_can_create_social_account_without_exposing_credential_secret(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    organization, _other_organization = organizations
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=["PUBLISH"],
    )
    client = create_member(organization=organization, role=roles[Role.Code.ADMINISTRATOR], username="admin")

    response = client.post(
        "/api/v1/social-accounts",
        {
            "platform": str(platform.id),
            "credential": str(credential.id),
            "external_id": "acme-linkedin",
            "display_name": "Acme LinkedIn",
            "publish_mode": "EXPORT_PACKAGE",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": response.json()["id"], "platform_id": str(platform.id),
        "display_name": "Acme LinkedIn", "publish_mode": "EXPORT_PACKAGE",
        "status": "ACTIVE", "effective_capabilities": [],
        "credential_configured": True,
        "connection_state": "CONFIGURATION_REQUIRED", "last_probe_at": None,
        "last_refresh_at": None, "reauthorization_required_at": None,
        "disconnected_at": None, "lifecycle_error_code": "",
        "provider": "DIRECT", "provider_channel_display_id": "••••edin",
        "is_locked": False, "is_queue_paused": False,
        "provider_last_sync_at": None,
    }
    assert "secret_reference" not in response.json()
    assert "vault://linkedin/acme" not in response.content.decode()


@pytest.mark.django_db
def test_lower_privilege_member_cannot_create_social_account(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    client = create_member(organization=organizations[0], role=roles[Role.Code.REVIEWER], username="reviewer")

    response = client.post(
        "/api/v1/social-accounts",
        {"platform": str(platform.id), "external_id": "acme-linkedin", "display_name": "Acme LinkedIn", "publish_mode": "MANUAL"},
        format="json",
    )

    assert response.status_code == 403
    assert client.get("/api/v1/social-accounts").status_code == 200


@pytest.mark.django_db
def test_publishing_reader_gets_safe_account_list_and_detail(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role], monkeypatch
) -> None:
    organization, other = organizations
    PlatformCapability.objects.create(platform=platform, code="PUBLISH")
    monkeypatch.setitem(CONNECTOR_CAPABILITIES, platform.code, frozenset({AccountCapability.PUBLISH}))
    credential = ConnectorCredential.objects.create(
        organization=organization, platform=platform,
        secret_reference="vault://linkedin/reader-secret", granted_scopes=["PUBLISH"],
    )
    account = SocialAccount.objects.create(
        organization=organization, platform=platform, credential=credential,
        external_id="reader-linkedin", display_name="Reader LinkedIn", publish_mode="API_AUTO",
    )
    SocialAccount.objects.create(
        organization=other, platform=platform, external_id="foreign", display_name="Foreign secret",
    )
    client = create_member(
        organization=organization, role=roles[Role.Code.REVIEWER], username="safe-reader"
    )

    listing = client.get("/api/v1/social-accounts")
    detail = client.get(f"/api/v1/social-accounts/{account.id}")

    expected = {
        "id": str(account.id), "platform_id": str(platform.id),
        "display_name": "Reader LinkedIn", "publish_mode": "API_AUTO",
        "status": "ACTIVE", "effective_capabilities": ["PUBLISH"],
        "credential_configured": True,
        "connection_state": "CONFIGURATION_REQUIRED", "last_probe_at": None,
        "last_refresh_at": None, "reauthorization_required_at": None,
        "disconnected_at": None, "lifecycle_error_code": "",
        "provider": "DIRECT", "provider_channel_display_id": "••••edin",
        "is_locked": False, "is_queue_paused": False,
        "provider_last_sync_at": None,
    }
    assert listing.status_code == detail.status_code == 200
    assert listing.json() == {"results": [expected]}
    assert detail.json() == expected
    serialized = f"{listing.json()} {detail.json()}"
    assert str(credential.id) not in serialized
    assert "reader-secret" not in serialized
    assert "Foreign secret" not in serialized


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("metadata", "expected_locked", "expected_paused"),
    [
        ({"is_locked": True, "is_queue_paused": False}, True, False),
        ({"is_locked": False, "is_queue_paused": True}, False, True),
        ({}, False, False),
        ({"is_locked": "true", "is_queue_paused": 1}, False, False),
        (["malformed"], False, False),
    ],
)
def test_buffer_account_returns_only_normalized_safe_channel_summary(
    platform, organizations, roles, metadata, expected_locked, expected_paused,
):
    organization, _other = organizations
    synced_at = timezone.now().replace(microsecond=0)
    connection = ProviderConnection.objects.create(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer/never-return-this",
        external_id="buffer-organization-private",
        display_name="Buffer Organization",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
        last_sync_at=synced_at,
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        provider=SocialAccount.Provider.BUFFER,
        provider_connection=connection,
        provider_account_id="buffer-channel-secret-1234",
        external_id="provider-external-private",
        display_name="Safe Buffer Channel",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connection_state=SocialAccount.ConnectionState.CONNECTED,
        connector_metadata=metadata,
    )
    client = create_member(
        organization=organization, role=roles[Role.Code.REVIEWER], username="buffer-summary"
    )

    response = client.get(f"/api/v1/social-accounts/{account.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "BUFFER"
    assert data["provider_channel_display_id"] == "••••1234"
    assert data["is_locked"] is expected_locked
    assert data["is_queue_paused"] is expected_paused
    assert data["provider_last_sync_at"] == synced_at.isoformat().replace("+00:00", "Z")
    serialized = response.content.decode()
    for forbidden in (
        "never-return-this", "buffer-channel-secret-1234", "provider-external-private",
        "connector_metadata", "provider_metadata", "credential_reference",
    ):
        assert forbidden not in serialized


@pytest.mark.django_db
def test_direct_account_keeps_safe_provider_summary(
    platform, organizations, roles,
):
    organization, _other = organizations
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        external_id="direct-account-9876",
        display_name="Direct Account",
    )
    client = create_member(
        organization=organization, role=roles[Role.Code.REVIEWER], username="direct-summary"
    )

    data = client.get(f"/api/v1/social-accounts/{account.id}").json()

    assert data["provider"] == "DIRECT"
    assert data["provider_channel_display_id"] == "••••9876"
    assert data["is_locked"] is False
    assert data["is_queue_paused"] is False
    assert data["provider_last_sync_at"] is None


@pytest.mark.django_db
def test_social_account_list_query_count_is_constant_for_buffer_channels(
    django_assert_num_queries, platform, organizations, roles,
):
    organization, _other = organizations
    PlatformCapability.objects.create(platform=platform, code="PUBLISH")
    connection = ProviderConnection.objects.create(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
        credential_reference="vault://buffer/query-count",
        external_id="org-query-count",
        connection_state=ProviderConnection.ConnectionState.CONNECTED,
    )
    for index in range(4):
        SocialAccount.objects.create(
            organization=organization,
            platform=platform,
            provider=SocialAccount.Provider.BUFFER,
            provider_connection=connection,
            provider_account_id=f"channel-{index}",
            external_id=f"external-{index}",
            display_name=f"Channel {index}",
            publish_mode=SocialAccount.PublishMode.API_AUTO,
            connection_state=SocialAccount.ConnectionState.CONNECTED,
        )
    client = create_member(
        organization=organization, role=roles[Role.Code.REVIEWER], username="channel-query-count"
    )

    with django_assert_num_queries(7):
        response = client.get("/api/v1/social-accounts")

    assert response.status_code == 200
    assert len(response.json()["results"]) == 4


@pytest.mark.django_db
def test_social_account_patch_is_strict_managed_and_organization_scoped(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    own, other = organizations
    own_credential = ConnectorCredential.objects.create(
        organization=own, platform=platform, secret_reference="vault://own", granted_scopes=[]
    )
    foreign_credential = ConnectorCredential.objects.create(
        organization=other, platform=platform, secret_reference="vault://foreign", granted_scopes=[]
    )
    own_account = SocialAccount.objects.create(
        organization=own, platform=platform, external_id="own", display_name="Before"
    )
    foreign_account = SocialAccount.objects.create(
        organization=other, platform=platform, external_id="foreign", display_name="Foreign"
    )
    admin = create_member(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="patch-admin")
    reader = create_member(organization=own, role=roles[Role.Code.REVIEWER], username="patch-reader")

    assert reader.patch(
        f"/api/v1/social-accounts/{own_account.id}", {"display_name": "Nope"}, format="json"
    ).status_code == 403
    assert admin.get(f"/api/v1/social-accounts/{foreign_account.id}").status_code == 404
    assert admin.patch(
        f"/api/v1/social-accounts/{foreign_account.id}", {"display_name": "Nope"}, format="json"
    ).status_code == 404
    assert admin.patch(
        f"/api/v1/social-accounts/{own_account.id}", {"external_id": "changed"}, format="json"
    ).status_code == 400
    assert admin.patch(
        f"/api/v1/social-accounts/{own_account.id}", {"credential": str(foreign_credential.id)}, format="json"
    ).status_code == 400

    updated = admin.patch(
        f"/api/v1/social-accounts/{own_account.id}",
        {"display_name": "After", "publish_mode": "MANUAL", "status": "INACTIVE", "credential": str(own_credential.id)},
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "After"
    assert updated.json()["credential_configured"] is True
    assert str(own_credential.id) not in str(updated.json())


@pytest.mark.django_db
def test_connector_credentials_are_managed_write_only_and_scope_checked(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    own, _other = organizations
    PlatformCapability.objects.create(platform=platform, code="PUBLISH")
    admin = create_member(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="credential-admin")
    reader = create_member(organization=own, role=roles[Role.Code.REVIEWER], username="credential-reader")
    payload = {
        "platform": str(platform.id), "secret_reference": "vault://linkedin/top-secret",
        "granted_scopes": ["PUBLISH"], "expires_at": None,
    }

    assert reader.get("/api/v1/connector-credentials").status_code == 403
    assert reader.post("/api/v1/connector-credentials", payload, format="json").status_code == 403
    invalid = admin.post(
        "/api/v1/connector-credentials", {**payload, "granted_scopes": ["METRICS_READ"]}, format="json"
    )
    unknown = admin.post(
        "/api/v1/connector-credentials", {**payload, "unknown": "top-secret"}, format="json"
    )
    created = admin.post("/api/v1/connector-credentials", payload, format="json")

    assert invalid.status_code == unknown.status_code == 400
    assert created.status_code == 201
    credential_id = created.json()["id"]
    expected = {
        "id": credential_id, "platform_id": str(platform.id),
        "granted_scopes": ["PUBLISH"], "expires_at": None, "configured": True,
    }
    assert created.json() == expected
    assert "top-secret" not in created.content.decode()
    assert admin.get("/api/v1/connector-credentials").json() == {"results": [expected]}

    updated = admin.patch(
        f"/api/v1/connector-credentials/{credential_id}",
        {"secret_reference": "vault://linkedin/replaced", "granted_scopes": []}, format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    assert "replaced" not in updated.content.decode()


@pytest.mark.django_db
def test_atomic_account_connection_supports_modes_and_rolls_back_credentials(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role],
) -> None:
    own, _other = organizations
    PlatformCapability.objects.create(platform=platform, code="PUBLISH")
    client = create_member(organization=own, role=roles[Role.Code.ADMINISTRATOR], username="atomic-admin")
    base = {
        "platform": str(platform.id), "display_name": "Channel", "status": "ACTIVE",
    }

    manual = client.post(
        "/api/v1/social-accounts/connect",
        {**base, "external_id": "manual", "publish_mode": "MANUAL"}, format="json",
    )
    export = client.post(
        "/api/v1/social-accounts/connect",
        {**base, "external_id": "export", "publish_mode": "EXPORT_PACKAGE"}, format="json",
    )
    automatic = client.post(
        "/api/v1/social-accounts/connect",
        {
            **base, "external_id": "automatic", "publish_mode": "API_AUTO",
            "secret_reference": "vault://atomic/private",
        }, format="json",
    )

    assert manual.status_code == export.status_code == automatic.status_code == 201
    assert ConnectorCredential.objects.filter(organization=own).count() == 1
    assert automatic.json()["credential_configured"] is True
    assert "private" not in automatic.content.decode()

    before = ConnectorCredential.objects.count()
    missing_secret = client.post(
        "/api/v1/social-accounts/connect",
        {**base, "external_id": "missing", "publish_mode": "API_AUTO"}, format="json",
    )
    duplicate_account = client.post(
        "/api/v1/social-accounts/connect",
        {
            **base, "external_id": "automatic", "publish_mode": "API_AUTO",
            "secret_reference": "vault://must-rollback",
        }, format="json",
    )

    assert missing_secret.status_code == duplicate_account.status_code == 400
    assert ConnectorCredential.objects.count() == before
    assert "must-rollback" not in duplicate_account.content.decode()


@pytest.mark.django_db
def test_social_accounts_are_organization_isolated_and_reject_foreign_credential(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    own_organization, other_organization = organizations
    other_credential = ConnectorCredential.objects.create(
        organization=other_organization,
        platform=platform,
        secret_reference="vault://linkedin/other",
    )
    SocialAccount.objects.create(
        organization=other_organization,
        platform=platform,
        credential=other_credential,
        external_id="other-linkedin",
        display_name="Other LinkedIn",
    )
    client = create_member(organization=own_organization, role=roles[Role.Code.ADMINISTRATOR], username="admin")

    listing = client.get("/api/v1/social-accounts")
    creation = client.post(
        "/api/v1/social-accounts",
        {"platform": str(platform.id), "credential": str(other_credential.id), "external_id": "acme-linkedin", "display_name": "Acme LinkedIn", "publish_mode": "MANUAL"},
        format="json",
    )

    assert listing.status_code == 200
    assert listing.json()["results"] == []
    assert creation.status_code == 400
    assert "credential" in creation.json()


@pytest.mark.django_db
def test_credential_platform_mismatch_is_rejected(
    platform: Platform, organizations: tuple[Organization, Organization], roles: dict[str, Role]
) -> None:
    other_platform = Platform.objects.create(code="YOUTUBE", name="YouTube")
    credential = ConnectorCredential.objects.create(
        organization=organizations[0], platform=other_platform, secret_reference="vault://youtube/acme"
    )
    client = create_member(organization=organizations[0], role=roles[Role.Code.ADMINISTRATOR], username="admin")

    response = client.post(
        "/api/v1/social-accounts",
        {"platform": str(platform.id), "credential": str(credential.id), "external_id": "acme-linkedin", "display_name": "Acme LinkedIn", "publish_mode": "MANUAL"},
        format="json",
    )

    assert response.status_code == 400
    assert "credential" in response.json()


@pytest.mark.django_db
def test_capability_codes_and_credential_scopes_are_validated(platform: Platform, organizations: tuple[Organization, Organization]) -> None:
    invalid_capability = PlatformCapability(platform=platform, code="NOT_A_CAPABILITY")
    invalid_scopes = ConnectorCredential(
        organization=organizations[0], platform=platform, secret_reference="vault://linkedin/acme", granted_scopes="PUBLISH"
    )
    unknown_scope = ConnectorCredential(
        organization=organizations[0], platform=platform, secret_reference="vault://linkedin/acme", granted_scopes=["UNKNOWN"]
    )

    with pytest.raises(ValidationError):
        invalid_capability.full_clean()
    with pytest.raises(ValidationError):
        invalid_scopes.full_clean()
    with pytest.raises(ValidationError):
        unknown_scope.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("malformed_scope", [{"code": "PUBLISH"}, ["PUBLISH"]])
def test_credential_scope_members_must_be_strings(
    platform: Platform, organizations: tuple[Organization, Organization], malformed_scope: object
) -> None:
    credential = ConnectorCredential(
        organization=organizations[0],
        platform=platform,
        secret_reference="vault://linkedin/acme",
        granted_scopes=[malformed_scope],
    )

    with pytest.raises(ValidationError):
        credential.full_clean()


@pytest.mark.django_db
def test_seed_platforms_is_idempotent_and_does_not_register_connectors() -> None:
    call_command("seed_platforms")
    call_command("seed_platforms")

    assert Platform.objects.count() == 11
    assert set(Platform.objects.values_list("code", flat=True)) == {
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "YOUTUBE", "TIKTOK", "DOUYIN", "KUAISHOU",
        "WECHAT_OFFICIAL_ACCOUNT", "WECHAT_CHANNELS", "XIAOHONGSHU", "BILIBILI",
    }
