from types import SimpleNamespace

import pytest
from django.db import transaction
from rest_framework.test import APIClient

from apps.identity.models import Role
from apps.identity.permissions import PermissionCode
from apps.platforms.permissions import CanAdministerBuffer

from .buffer_test_utils import authenticated_member


BUFFER_ENDPOINTS = (
    ("get", "/api/v1/provider-connections/buffer", None),
    ("post", "/api/v1/provider-connections/buffer", {}),
    ("patch", "/api/v1/provider-connections/buffer", {}),
    ("post", "/api/v1/provider-connections/buffer/probe", {}),
    ("post", "/api/v1/provider-connections/buffer/sync", {}),
    ("post", "/api/v1/provider-connections/buffer/disconnect", {"confirm": True}),
)


def _call(client, method, path, payload):
    if payload is None:
        return getattr(client, method)(path)
    return getattr(client, method)(path, payload, format="json")


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "path", "payload"), BUFFER_ENDPOINTS)
def test_all_buffer_admin_endpoints_require_administrator_and_both_permissions(
    organization, method, path, payload,
):
    role = Role.objects.get(code=Role.Code.OPERATOR)
    role.permissions = [PermissionCode.CREDENTIALS_MANAGE, PermissionCode.PUBLISHING_READ]
    role.save(update_fields=["permissions"])
    client, _user = authenticated_member(
        organization=organization, role=role, prefix=f"not-admin-{method}"
    )

    assert _call(client, method, path, payload).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "permissions",
    [
        [PermissionCode.PUBLISHING_READ],
        [PermissionCode.CREDENTIALS_MANAGE],
    ],
)
@pytest.mark.parametrize(("method", "path", "payload"), BUFFER_ENDPOINTS)
def test_all_buffer_admin_endpoints_reject_missing_required_permission(
    organization, permissions, method, path, payload,
):
    role = Role.objects.get(code=Role.Code.ADMINISTRATOR)
    role.permissions = permissions
    role.save(update_fields=["permissions"])
    client, _user = authenticated_member(
        organization=organization, role=role, prefix=f"restricted-{method}"
    )

    assert _call(client, method, path, payload).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "path", "payload"), BUFFER_ENDPOINTS)
def test_all_buffer_admin_endpoints_reject_anonymous(method, path, payload):
    assert _call(APIClient(), method, path, payload).status_code in {401, 403}


@pytest.mark.django_db
@pytest.mark.parametrize(("method", "path", "payload"), BUFFER_ENDPOINTS)
def test_full_buffer_administrator_reaches_each_endpoint(
    admin_client, method, path, payload,
):
    client, _user = admin_client
    assert _call(client, method, path, payload).status_code != 403


@pytest.mark.django_db(transaction=True)
def test_buffer_administrator_permission_sets_tenant_before_view_queries(
    admin_client, monkeypatch
):
    _client, user = admin_client
    request = SimpleNamespace(user=user)
    tenant_ids = []
    monkeypatch.setattr(
        "apps.platforms.permissions.set_local_tenant",
        tenant_ids.append,
    )

    with transaction.atomic():
        assert CanAdministerBuffer().has_permission(request, object()) is True

    assert tenant_ids == [request.membership.organization_id]
    assert request.organization == request.membership.organization
