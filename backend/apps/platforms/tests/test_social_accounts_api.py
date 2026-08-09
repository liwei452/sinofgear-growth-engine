import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import ConnectorCredential, Platform, PlatformCapability, SocialAccount


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
    with django_assert_num_queries(5):
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
    assert response.json()["organization"] == str(organization.id)
    assert response.json()["credential"] == str(credential.id)
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
    assert client.get("/api/v1/social-accounts").status_code == 403


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
