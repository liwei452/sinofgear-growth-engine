import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

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


@pytest.mark.django_db(transaction=True)
def test_phase_b1_permission_migration_reverse_preserves_role_permission_data():
    before = ("identity", "0010_phaseae2eownership")
    after = ("identity", "0011_refresh_phase_b1_permissions")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([before])
        old_role_model = executor.loader.project_state([before]).apps.get_model("identity", "Role")
        role, _ = old_role_model.objects.update_or_create(
            code="ADMINISTRATOR",
            defaults={
                "name": "Administrator",
                "permissions": ["custom.before", "sources.read"],
            },
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        new_role_model = executor.loader.project_state([after]).apps.get_model("identity", "Role")
        migrated_role = new_role_model.objects.get(pk=role.pk)
        migrated_role.permissions.append("custom.after")
        migrated_role.save(update_fields=["permissions"])

        executor = MigrationExecutor(connection)
        executor.migrate([before])
        restored_role_model = executor.loader.project_state([before]).apps.get_model("identity", "Role")
        restored_permissions = restored_role_model.objects.get(pk=role.pk).permissions

        assert "sources.read" in restored_permissions
        assert "custom.before" in restored_permissions
        assert "custom.after" in restored_permissions
    finally:
        MigrationExecutor(connection).migrate(latest)
