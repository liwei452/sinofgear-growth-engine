import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from apps.identity.models import Role


@pytest.mark.django_db
def test_task_five_upgrade_migration_refreshes_stale_builtin_roles() -> None:
    loader = MigrationLoader(connection)
    migration_key = ("identity", "0002_refresh_builtin_role_permissions")
    assert migration_key in loader.disk_migrations
    stale_roles = [
        Role.objects.update_or_create(
            code=code,
            defaults={"name": str(code), "permissions": ["stale.permission"]},
        )[0]
        for code in Role.Code.values
    ]

    migration = importlib.import_module("apps.identity.migrations.0002_refresh_builtin_role_permissions")
    migration.refresh_builtin_role_permissions(django_apps, None)

    for stale in stale_roles:
        stale.refresh_from_db()
        assert "stale.permission" not in stale.permissions
        assert "knowledge.read" in stale.permissions
    assert "knowledge.manage_system" in Role.objects.get(code="ADMINISTRATOR").permissions
    assert "knowledge.create" in Role.objects.get(code="OPERATOR").permissions
    assert "knowledge.review_organization" in Role.objects.get(code="REVIEWER").permissions
    assert Role.objects.get(code="READ_ONLY").permissions == ["memberships.read", "knowledge.read"]


@pytest.mark.django_db
def test_task_seven_upgrade_migration_refreshes_stale_asset_permissions() -> None:
    loader = MigrationLoader(connection)
    migration_key = ("identity", "0004_refresh_asset_permissions")
    assert migration_key in loader.disk_migrations
    for code in Role.Code.values:
        Role.objects.update_or_create(
            code=code,
            defaults={"name": str(code), "permissions": ["stale.permission"]},
        )

    migration = importlib.import_module(
        "apps.identity.migrations.0004_refresh_asset_permissions"
    )
    migration.refresh_builtin_role_permissions(django_apps, None)

    administrator = Role.objects.get(code=Role.Code.ADMINISTRATOR)
    operator = Role.objects.get(code=Role.Code.OPERATOR)
    reviewer = Role.objects.get(code=Role.Code.REVIEWER)
    read_only = Role.objects.get(code=Role.Code.READ_ONLY)
    assert {"assets.read", "assets.manage"} <= set(administrator.permissions)
    assert {"assets.read", "assets.manage"} <= set(operator.permissions)
    assert "assets.read" in reviewer.permissions
    assert "assets.manage" not in reviewer.permissions
    assert "assets.read" in read_only.permissions
    assert "assets.manage" not in read_only.permissions
    assert all(
        "stale.permission" not in role.permissions
        for role in (administrator, operator, reviewer, read_only)
    )
