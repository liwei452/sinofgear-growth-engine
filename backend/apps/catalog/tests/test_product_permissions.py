import importlib

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from apps.identity.models import Role


@pytest.mark.django_db
def test_builtin_roles_include_product_permissions() -> None:
    administrator = Role.objects.create_administrator()
    operator = Role.objects.create_operator()
    reviewer = Role.objects.create_reviewer()
    read_only = Role.objects.create_read_only()

    assert {"products.read", "products.manage"} <= set(administrator.permissions)
    assert {"products.read", "products.manage"} <= set(operator.permissions)
    assert "products.read" in reviewer.permissions and "products.manage" not in reviewer.permissions
    assert "products.read" in read_only.permissions and "products.manage" not in read_only.permissions


@pytest.mark.django_db
def test_task_six_upgrade_migration_refreshes_existing_builtin_roles() -> None:
    loader = MigrationLoader(connection)
    migration_key = ("identity", "0003_refresh_product_permissions")
    assert migration_key in loader.disk_migrations
    for code in Role.Code.values:
        Role.objects.update_or_create(
            code=code,
            defaults={"name": str(code), "permissions": ["stale.permission"]},
        )

    migration = importlib.import_module("apps.identity.migrations.0003_refresh_product_permissions")
    migration.refresh_builtin_role_permissions(django_apps, None)

    assert {"products.read", "products.manage"} <= set(
        Role.objects.get(code=Role.Code.ADMINISTRATOR).permissions
    )
    assert {"products.read", "products.manage"} <= set(
        Role.objects.get(code=Role.Code.OPERATOR).permissions
    )
    assert "products.read" in Role.objects.get(code=Role.Code.REVIEWER).permissions
    assert "products.manage" not in Role.objects.get(code=Role.Code.REVIEWER).permissions
    assert "products.read" in Role.objects.get(code=Role.Code.READ_ONLY).permissions
    assert all(
        "stale.permission" not in role.permissions
        for role in Role.objects.filter(code__in=Role.Code.values)
    )
