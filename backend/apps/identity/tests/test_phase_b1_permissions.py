import pytest

from apps.identity.models import Role
from apps.identity.permissions import PermissionCode


def test_phase_b1_permission_codes_are_stable():
    assert {code.value for code in PermissionCode if code.value.startswith(("sources.", "leads."))} == {
        "sources.read",
        "sources.manage",
        "leads.read",
        "leads.analyze",
        "leads.review",
        "leads.handoff",
    }


@pytest.mark.django_db
def test_builtin_roles_grant_phase_b1_permissions_by_responsibility():
    roles = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator(),
        Role.Code.OPERATOR: Role.objects.create_operator(),
        Role.Code.REVIEWER: Role.objects.create_reviewer(),
        Role.Code.READ_ONLY: Role.objects.create_read_only(),
    }

    expected = {
        Role.Code.ADMINISTRATOR: {
            "sources.read", "sources.manage", "leads.read", "leads.analyze", "leads.review", "leads.handoff",
        },
        Role.Code.OPERATOR: {"sources.read", "sources.manage", "leads.read", "leads.analyze"},
        Role.Code.REVIEWER: {"sources.read", "leads.read", "leads.review"},
        Role.Code.READ_ONLY: {"sources.read", "leads.read"},
    }

    for code, role in roles.items():
        assert set(role.permissions) & {permission.value for permission in PermissionCode if permission.value.startswith(("sources.", "leads."))} == expected[code]
