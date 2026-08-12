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
    JOBS_READ = "jobs.read"
    JOBS_MANAGE = "jobs.manage"
    CONTENT_READ = "content.read"
    CONTENT_MANAGE = "content.manage"
    CONTENT_REVIEW = "content.review"
    PUBLISHING_READ = "publishing.read"
    PUBLISHING_MANAGE = "publishing.manage"
    TRACKING_READ = "tracking.read"
    TRACKING_MANAGE = "tracking.manage"
    SOURCES_READ = "sources.read"
    SOURCES_MANAGE = "sources.manage"
    LEADS_READ = "leads.read"
    LEADS_ANALYZE = "leads.analyze"
    LEADS_REVIEW = "leads.review"
    LEADS_HANDOFF = "leads.handoff"
    DIRECTOR_READ = "director.read"
    DIRECTOR_DECIDE = "director.decide"


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


class CanReadJobs(HasOrganizationPermission):
    permission_code = PermissionCode.JOBS_READ


class CanManageJobs(HasOrganizationPermission):
    permission_code = PermissionCode.JOBS_MANAGE


class CanReadContent(HasOrganizationPermission):
    permission_code = PermissionCode.CONTENT_READ


class CanManageContent(HasOrganizationPermission):
    permission_code = PermissionCode.CONTENT_MANAGE


class CanReviewContent(HasOrganizationPermission):
    permission_code = PermissionCode.CONTENT_REVIEW


class CanReadPublishing(HasOrganizationPermission):
    permission_code = PermissionCode.PUBLISHING_READ


class CanManagePublishing(HasOrganizationPermission):
    permission_code = PermissionCode.PUBLISHING_MANAGE


class CanReadTracking(HasOrganizationPermission):
    permission_code = PermissionCode.TRACKING_READ


class CanManageTracking(HasOrganizationPermission):
    permission_code = PermissionCode.TRACKING_MANAGE


class CanReadSources(HasOrganizationPermission):
    permission_code = PermissionCode.SOURCES_READ


class CanManageSources(HasOrganizationPermission):
    permission_code = PermissionCode.SOURCES_MANAGE


class CanReadLeads(HasOrganizationPermission):
    permission_code = PermissionCode.LEADS_READ


class CanAnalyzeLeads(HasOrganizationPermission):
    permission_code = PermissionCode.LEADS_ANALYZE


class CanReviewLeads(HasOrganizationPermission):
    permission_code = PermissionCode.LEADS_REVIEW


class CanHandoffLeads(HasOrganizationPermission):
    permission_code = PermissionCode.LEADS_HANDOFF


class CanReadDirector(HasOrganizationPermission):
    permission_code = PermissionCode.DIRECTOR_READ


class CanDecideDirector(HasOrganizationPermission):
    permission_code = PermissionCode.DIRECTOR_DECIDE
