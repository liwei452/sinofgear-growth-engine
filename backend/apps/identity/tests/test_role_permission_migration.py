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
