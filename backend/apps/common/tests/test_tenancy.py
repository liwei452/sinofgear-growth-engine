from uuid import UUID, uuid4

import pytest
from django.db import connection

from apps.common.tenancy import TenantContextError, set_local_tenant, tenant_atomic


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "invalid_organization_id",
    [None, "00000000-0000-4000-8000-000000000001", 1, True],
)
def test_tenant_context_rejects_non_native_uuid(invalid_organization_id):
    with pytest.raises(TypeError, match="native UUID"):
        with tenant_atomic(invalid_organization_id):
            pass


@pytest.mark.django_db(transaction=True)
def test_set_local_tenant_requires_an_active_transaction():
    assert not connection.in_atomic_block

    with pytest.raises(TenantContextError, match="active database transaction"):
        set_local_tenant(uuid4())


@pytest.mark.django_db(transaction=True)
def test_nested_tenant_context_reuses_same_organization_and_rejects_switch():
    organization_id = uuid4()

    with tenant_atomic(organization_id):
        assert connection.in_atomic_block
        with tenant_atomic(organization_id):
            assert connection.in_atomic_block
        with pytest.raises(TenantContextError, match="cannot switch"):
            with tenant_atomic(uuid4()):
                pass

    assert not connection.in_atomic_block


@pytest.mark.django_db(transaction=True)
def test_tenant_context_exits_after_rollback():
    organization_id = uuid4()

    with pytest.raises(RuntimeError, match="rollback"):
        with tenant_atomic(organization_id):
            raise RuntimeError("rollback")

    with tenant_atomic(UUID("00000000-0000-4000-8000-000000000002")):
        assert connection.in_atomic_block
