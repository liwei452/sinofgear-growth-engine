from rest_framework.permissions import BasePermission

from apps.common.tenancy import set_local_tenant
from apps.identity.models import Membership, Role
from apps.identity.permissions import PermissionCode
from apps.identity.services import get_active_membership


class CanAdministerBuffer(BasePermission):
    """Require the complete role and permission boundary for Buffer administration."""

    def has_permission(self, request, view) -> bool:
        del view
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            membership = get_active_membership(user=request.user)
        except Membership.DoesNotExist:
            return False
        permissions = membership.role.permissions
        allowed = (
            type(permissions) is list
            and membership.role.code == Role.Code.ADMINISTRATOR
            and PermissionCode.CREDENTIALS_MANAGE in permissions
            and PermissionCode.PUBLISHING_READ in permissions
        )
        if allowed:
            request.membership = membership
            request.organization = membership.organization
            set_local_tenant(membership.organization_id)
        return allowed
