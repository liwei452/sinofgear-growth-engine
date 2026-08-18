import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.identity.permissions import PermissionCode
from apps.identity.services import require_permission


@pytest.fixture
def organization() -> Organization:
    return Organization.objects.create(name="Acme", slug="acme")


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


def create_membership(*, organization: Organization, role: Role, username: str) -> Membership:
    user = get_user_model().objects.create_user(username=username, password="correct-horse-battery-staple")
    return Membership.objects.create(user=user, organization=organization, role=role)


@pytest.mark.django_db
def test_read_only_member_cannot_execute_membership_write_action(
    organization: Organization, roles: dict[str, Role]
) -> None:
    membership = create_membership(
        organization=organization, role=roles[Role.Code.READ_ONLY], username="read-only"
    )
    client = APIClient()
    assert client.login(username="read-only", password="correct-horse-battery-staple")

    response = client.patch(
        f"/api/v1/memberships/{membership.id}",
        {"status": Membership.Status.INACTIVE},
        format="json",
    )

    assert response.status_code == 403
    membership.refresh_from_db()
    assert membership.status == Membership.Status.ACTIVE


@pytest.mark.django_db
def test_operator_cannot_escalate_membership_role(
    organization: Organization, roles: dict[str, Role]
) -> None:
    membership = create_membership(
        organization=organization, role=roles[Role.Code.OPERATOR], username="operator"
    )
    client = APIClient()
    assert client.login(username="operator", password="correct-horse-battery-staple")

    response = client.patch(
        f"/api/v1/memberships/{membership.id}",
        {"role": str(roles[Role.Code.ADMINISTRATOR].id)},
        format="json",
    )

    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.role.code == Role.Code.OPERATOR


@pytest.mark.django_db
def test_reviewer_cannot_manage_connector_credentials(
    organization: Organization, roles: dict[str, Role]
) -> None:
    membership = create_membership(
        organization=organization, role=roles[Role.Code.REVIEWER], username="reviewer"
    )

    with pytest.raises(PermissionDenied, match="Missing permission: credentials.manage"):
        require_permission(membership=membership, permission=PermissionCode.CREDENTIALS_MANAGE)


@pytest.mark.django_db
def test_builtin_roles_receive_mission_permissions() -> None:
    assert "missions.manage" in Role.objects.create_administrator().permissions
    assert "missions.review" in Role.objects.create_administrator().permissions
    assert "missions.manage" not in Role.objects.create_operator().permissions
    assert "missions.review" not in Role.objects.create_reviewer().permissions
    assert Role.objects.create_read_only().permissions.count("missions.read") == 1
    assert "missions.manage" not in Role.objects.create_read_only().permissions


@pytest.mark.django_db
def test_seed_initial_organization_creates_roles_and_administrator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "strong-test-password")
    monkeypatch.setenv("SEED_ADMIN_USERNAME", "bootstrap-admin")

    call_command("seed_initial_organization")
    call_command("seed_initial_organization")

    membership = Membership.objects.get(user__username="bootstrap-admin")
    assert membership.role.code == Role.Code.ADMINISTRATOR
    assert Organization.objects.count() == 1
    assert Role.objects.count() == 4
