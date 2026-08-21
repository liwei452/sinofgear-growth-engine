from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID

from django.db.models import Model

from apps.common.tenancy import tenant_atomic
from apps.identity.models import Organization


class TenantTaskError(ValueError):
    """Raised when a background task cannot establish a safe tenant boundary."""


def parse_tenant_organization_id(value: object) -> UUID:
    """Parse a Celery organization argument without accepting coercible values."""

    if type(value) is not str or not value or value != value.strip():
        raise TenantTaskError("organization_id must be a valid UUID string.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise TenantTaskError("organization_id must be a valid UUID string.") from exc


@contextmanager
def tenant_task_context(organization_id: str) -> Iterator[UUID]:
    """Enter a transaction-local tenant context before any tenant ORM access."""

    parsed = parse_tenant_organization_id(organization_id)
    with tenant_atomic(parsed):
        yield parsed


ModelT = TypeVar("ModelT", bound=Model)


def require_tenant_object(
    model: type[ModelT],
    organization_id: UUID,
    /,
    **lookup: Any,
) -> ModelT:
    """Load an object using both RLS and an explicit organization predicate."""

    try:
        return model._default_manager.get(organization_id=organization_id, **lookup)
    except model.DoesNotExist as exc:
        raise TenantTaskError("Tenant task target is unavailable.") from exc


@dataclass(frozen=True)
class TenantWorkResult:
    consumed: int = 0
    counters: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        if type(self.consumed) is not int or self.consumed < 0:
            raise TenantTaskError("Tenant work consumed count must be non-negative.")
        for key, value in (self.counters or {}).items():
            if type(key) is not str or type(value) is not int or value < 0:
                raise TenantTaskError("Tenant work counters must be non-negative integers.")


TenantOperation = Callable[[UUID, int | None], TenantWorkResult]


def materialize_tenant_organization_ids() -> tuple[UUID, ...]:
    """Read only the control-plane IDs, fully materialized in stable order."""

    return tuple(Organization.objects.order_by("id").values_list("id", flat=True))


def resolve_control_plane_organization_ids(value: object | None = None) -> tuple[UUID, ...]:
    """Resolve one requested control-plane organization, or enumerate all."""

    if value is None:
        return materialize_tenant_organization_ids()
    organization_id = parse_tenant_organization_id(value)
    if not Organization.objects.filter(pk=organization_id).exists():
        raise TenantTaskError("organization_id is unavailable.")
    return (organization_id,)


def run_tenant_coordinator(
    operation: TenantOperation,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    """Run bounded tenant work in independent transactions and aggregate safe counts."""

    if limit is not None and (type(limit) is not int or limit < 0):
        raise TenantTaskError("Coordinator limit must be a non-negative integer.")

    totals: Counter[str] = Counter()
    consumed = 0
    organizations = 0
    for organization_id in materialize_tenant_organization_ids():
        remaining = None if limit is None else limit - consumed
        if remaining == 0:
            break
        with tenant_atomic(organization_id):
            result = operation(organization_id, remaining)
        if not isinstance(result, TenantWorkResult):
            raise TenantTaskError("Tenant operation returned an invalid result.")
        if remaining is not None and result.consumed > remaining:
            raise TenantTaskError("Tenant operation exceeded the global limit.")
        consumed += result.consumed
        totals.update(result.counters or {})
        organizations += 1

    return {"organizations": organizations, "consumed": consumed, **dict(totals)}
