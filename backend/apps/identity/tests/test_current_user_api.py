import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role


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
        for role in (
            Role.objects.create_administrator(),
            Role.objects.create_operator(),
            Role.objects.create_reviewer(),
            Role.objects.create_read_only(),
        )
    }


@pytest.fixture
def authenticated_client(organizations: tuple[Organization, Organization], roles: dict[str, Role]) -> tuple[APIClient, Membership, Membership]:
    user_model = get_user_model()
    user = user_model.objects.create_user(username="operator", password="correct-horse-battery-staple")
    own_membership = Membership.objects.create(
        user=user,
        organization=organizations[0],
        role=roles[Role.Code.OPERATOR],
    )
    other_user = user_model.objects.create_user(username="other", password="correct-horse-battery-staple")
    other_membership = Membership.objects.create(
        user=other_user,
        organization=organizations[1],
        role=roles[Role.Code.OPERATOR],
    )
    client = APIClient()
    assert client.login(username="operator", password="correct-horse-battery-staple")
    return client, own_membership, other_membership


@pytest.mark.django_db
def test_me_uses_authenticated_membership_organization_ignoring_requested_organization(
    authenticated_client: tuple[APIClient, Membership, Membership],
) -> None:
    client, own_membership, other_membership = authenticated_client

    response = client.get(f"/api/v1/auth/me?organization_id={other_membership.organization_id}")

    assert response.status_code == 200
    assert response.json()["organization"]["id"] == str(own_membership.organization_id)
    assert response.json()["organization"]["id"] != str(other_membership.organization_id)


@pytest.mark.django_db
def test_me_returns_only_authenticated_membership_permissions_in_stable_order(
    authenticated_client: tuple[APIClient, Membership, Membership],
) -> None:
    client, own_membership, other_membership = authenticated_client
    own_membership.role.permissions = [
        "products.manage",
        "memberships.read",
        "knowledge.read",
        "products.read",
    ]
    own_membership.role.save(update_fields=["permissions"])
    foreign_role = Role.objects.create(
        code="FOREIGN_TEST",
        name="Foreign test role",
        permissions=["knowledge.manage_system", "memberships.manage"],
    )
    other_membership.role = foreign_role
    other_membership.save(update_fields=["role"])

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["membership"]["permissions"] == [
        "knowledge.read",
        "memberships.read",
        "products.manage",
        "products.read",
    ]
    assert "knowledge.manage_system" not in response.json()["membership"]["permissions"]


@pytest.mark.django_db
def test_membership_in_another_organization_is_not_readable_or_mutable(
    authenticated_client: tuple[APIClient, Membership, Membership],
) -> None:
    client, _own_membership, other_membership = authenticated_client
    url = f"/api/v1/memberships/{other_membership.id}"

    assert client.get(url).status_code == 404
    assert client.patch(url, {"status": Membership.Status.INACTIVE}, format="json").status_code == 404
    other_membership.refresh_from_db()
    assert other_membership.status == Membership.Status.ACTIVE


@pytest.mark.django_db
def test_login_does_not_disclose_whether_a_user_exists() -> None:
    client = APIClient()
    get_user_model().objects.create_user(username="existing", password="correct-horse-battery-staple")

    missing_user = client.post("/api/v1/auth/login", {"username": "missing", "password": "bad"}, format="json")
    wrong_password = client.post("/api/v1/auth/login", {"username": "existing", "password": "bad"}, format="json")

    assert missing_user.status_code == wrong_password.status_code == 400
    assert missing_user.json() == wrong_password.json() == {"detail": "Invalid credentials."}


@pytest.mark.django_db
def test_csrf_bootstrap_sets_cookie_and_login_requires_matching_header() -> None:
    get_user_model().objects.create_user(username="csrf-user", password="safe-password")
    client = APIClient(enforce_csrf_checks=True)

    bootstrap = client.get("/api/v1/auth/csrf")

    assert bootstrap.status_code == 204
    assert bootstrap.cookies["csrftoken"].value
    credentials = {"username": "csrf-user", "password": "safe-password"}
    assert client.post("/api/v1/auth/login", credentials, format="json").status_code == 403
    token = bootstrap.cookies["csrftoken"].value
    assert client.post(
        "/api/v1/auth/login", credentials, format="json", HTTP_X_CSRFTOKEN=token
    ).status_code == 204
