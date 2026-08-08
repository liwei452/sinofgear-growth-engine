from enum import StrEnum

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

class PermissionCode(StrEnum):
    MEMBERSHIPS_READ = "memberships.read"
    MEMBERSHIPS_MANAGE = "memberships.manage"
    CREDENTIALS_MANAGE = "credentials.manage"


class HasOrganizationPermission(BasePermission):
    permission_code: PermissionCode

    def has_permission(self, request, view) -> bool:
        from .models import Membership
        from .services import get_active_membership, require_permission

        if not request.user or not request.user.is_authenticated:
            return False
        try:
            membership = get_active_membership(user=request.user)
            require_permission(membership=membership, permission=self.permission_code)
        except (Membership.DoesNotExist, PermissionDenied):
            return False
        request.membership = membership
        request.organization = membership.organization
        return True


class CanReadMemberships(HasOrganizationPermission):
    permission_code = PermissionCode.MEMBERSHIPS_READ


class CanManageMemberships(HasOrganizationPermission):
    permission_code = PermissionCode.MEMBERSHIPS_MANAGE
