from enum import StrEnum

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

class PermissionCode(StrEnum):
    MEMBERSHIPS_READ = "memberships.read"
    MEMBERSHIPS_MANAGE = "memberships.manage"
    CREDENTIALS_MANAGE = "credentials.manage"
    KNOWLEDGE_READ = "knowledge.read"
    KNOWLEDGE_CREATE = "knowledge.create"
    KNOWLEDGE_REVIEW_ORGANIZATION = "knowledge.review_organization"
    KNOWLEDGE_MANAGE_SYSTEM = "knowledge.manage_system"
    KNOWLEDGE_DEPRECATE = "knowledge.deprecate"
    PRODUCTS_READ = "products.read"
    PRODUCTS_MANAGE = "products.manage"
    ASSETS_READ = "assets.read"
    ASSETS_MANAGE = "assets.manage"
    CAMPAIGNS_READ = "campaigns.read"
    CAMPAIGNS_MANAGE = "campaigns.manage"
    CAMPAIGNS_REVIEW = "campaigns.review"


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


class CanManageCredentials(HasOrganizationPermission):
    permission_code = PermissionCode.CREDENTIALS_MANAGE


class CanReadKnowledge(HasOrganizationPermission):
    permission_code = PermissionCode.KNOWLEDGE_READ


class CanCreateKnowledge(HasOrganizationPermission):
    permission_code = PermissionCode.KNOWLEDGE_CREATE


class CanReviewOrganizationKnowledge(HasOrganizationPermission):
    permission_code = PermissionCode.KNOWLEDGE_REVIEW_ORGANIZATION


class CanDeprecateKnowledge(HasOrganizationPermission):
    permission_code = PermissionCode.KNOWLEDGE_DEPRECATE


class CanReadProducts(HasOrganizationPermission):
    permission_code = PermissionCode.PRODUCTS_READ


class CanManageProducts(HasOrganizationPermission):
    permission_code = PermissionCode.PRODUCTS_MANAGE


class CanReadAssets(HasOrganizationPermission):
    permission_code = PermissionCode.ASSETS_READ


class CanManageAssets(HasOrganizationPermission):
    permission_code = PermissionCode.ASSETS_MANAGE


class CanReadCampaigns(HasOrganizationPermission):
    permission_code = PermissionCode.CAMPAIGNS_READ


class CanManageCampaigns(HasOrganizationPermission):
    permission_code = PermissionCode.CAMPAIGNS_MANAGE


class CanReviewCampaigns(HasOrganizationPermission):
    permission_code = PermissionCode.CAMPAIGNS_REVIEW
