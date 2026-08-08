import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


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
    assert response.json()["results"] == [{"code": "LINKEDIN", "name": "LinkedIn", "capabilities": []}]


@pytest.mark.django_db
def test_anonymous_user_cannot_list_platforms() -> None:
    assert APIClient().get("/api/v1/platforms").status_code == 403


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
        implementation_capabilities=["PUBLISH"],
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
