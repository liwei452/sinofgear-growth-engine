from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied

from .models import Membership, Organization


def lock_organization_scope(*, organization) -> Organization:
    """Serialize organization-scoped immutable snapshot and retention changes."""
    organization_id = getattr(organization, "pk", organization)
    return Organization.objects.select_for_update().get(pk=organization_id)


def get_active_membership(*, user: AbstractUser) -> Membership:
    return Membership.objects.select_related("organization", "role").get(
        user=user,
        status=Membership.Status.ACTIVE,
    )


def require_permission(*, membership: Membership, permission: str) -> None:
    if permission not in membership.role.permissions:
        raise PermissionDenied(f"Missing permission: {permission}")
