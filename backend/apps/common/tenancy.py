from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from django.db import connection, transaction


TENANT_SETTING = "app.current_organization_id"


class TenantContextError(RuntimeError):
    """Raised when tenant database context is missing or unsafe."""


_active_tenant: ContextVar[UUID | None] = ContextVar(
    "active_database_tenant",
    default=None,
)


def _validate_organization_id(organization_id: UUID) -> None:
    if type(organization_id) is not UUID:
        raise TypeError("organization_id must be a native UUID instance.")


def set_local_tenant(organization_id: UUID) -> None:
    """Set the PostgreSQL tenant GUC for the current transaction only."""

    _validate_organization_id(organization_id)
    if not connection.in_atomic_block:
        raise TenantContextError("Tenant context requires an active database transaction.")

    if connection.vendor == "sqlite":
        # Compatibility mode only. SQLite does not provide row-level security.
        return
    if connection.vendor != "postgresql":
        raise TenantContextError(
            f"Tenant context is unsupported by database vendor {connection.vendor!r}."
        )

    tenant_value = str(organization_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT NULLIF(current_setting(%s, true), '')",
            [TENANT_SETTING],
        )
        current_value = cursor.fetchone()[0]
        if current_value is not None and current_value != tenant_value:
            raise TenantContextError("An active tenant transaction cannot switch organization.")
        if current_value is None:
            cursor.execute(
                "SELECT set_config(%s, %s, true)",
                [TENANT_SETTING, tenant_value],
            )


@contextmanager
def tenant_atomic(organization_id: UUID) -> Iterator[None]:
    """Open an atomic transaction scoped to one organization."""

    _validate_organization_id(organization_id)
    active_tenant = _active_tenant.get()
    if active_tenant is not None:
        if active_tenant != organization_id:
            raise TenantContextError("A nested tenant transaction cannot switch organization.")
        if not connection.in_atomic_block:
            raise TenantContextError("Tenant context requires an active database transaction.")
        yield
        return

    with transaction.atomic():
        set_local_tenant(organization_id)
        token = _active_tenant.set(organization_id)
        try:
            yield
        finally:
            _active_tenant.reset(token)
