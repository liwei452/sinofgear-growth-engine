from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist


class RLSCategory(StrEnum):
    TENANT_DIRECT = "TENANT_DIRECT"
    TENANT_PARENT = "TENANT_PARENT"
    TENANT_MIXED = "TENANT_MIXED"
    GLOBAL_CONTEXT_READ = "GLOBAL_CONTEXT_READ"
    CONTROL_PLANE = "CONTROL_PLANE"
    GLOBAL = "GLOBAL"


class RLSPhase(StrEnum):
    RLS_1 = "RLS-1"
    RLS_2A = "RLS-2A"
    RLS_2B = "RLS-2B"
    RLS_2C = "RLS-2C"
    EXEMPT = "EXEMPT"


@dataclass(frozen=True, slots=True)
class RLSManifestEntry:
    model_label: str
    db_table: str
    category: RLSCategory
    phase: RLSPhase
    organization_column: str | None = None
    parent_paths: tuple[str, ...] = ()
    rls1_covered: bool = False
    rationale: str = ""
    contains_credentials: bool = False
    contains_customer_content: bool = False
    contains_publishing_data: bool = False
    contains_audit_data: bool = False
    public_entry_access: bool = False
    background_task_access: bool = False


class RLSManifestError(RuntimeError):
    pass


EXCLUDED_DJANGO_APP_LABELS = {
    "admin": "Django administration log infrastructure.",
    "auth": "Django authentication and authorization control plane.",
    "contenttypes": "Django model metadata infrastructure.",
    "sessions": "Django session infrastructure.",
}
EXCLUDED_DJANGO_TABLES = {
    "django_migrations": "Django migration recorder; it is not an apps-registry model.",
}

RLS1_TABLES = frozenset(
    {
        "knowledge_companyknowledgeprofile",
        "knowledge_companyfact",
        "knowledge_companyfactevidence",
        "knowledge_icpprofile",
        "knowledge_icpproductlink",
        "knowledge_websitepage",
        "knowledge_websitepageproductlink",
        "knowledge_websitepageconceptlink",
        "knowledge_knowledgecontextsnapshot",
        "knowledge_knowledgeevidence",
        "knowledge_knowledgeconcept",
        "knowledge_knowledgealias",
        "knowledge_knowledgerelation",
        "knowledge_knowledgeconcept_evidence",
        "knowledge_knowledgerelation_evidence",
    }
)


def _direct(
    model_label: str,
    db_table: str,
    phase: RLSPhase,
    **metadata,
) -> RLSManifestEntry:
    return RLSManifestEntry(
        model_label=model_label,
        db_table=db_table,
        category=RLSCategory.TENANT_DIRECT,
        phase=phase,
        organization_column="organization_id",
        **metadata,
    )


def _parent(
    model_label: str,
    db_table: str,
    phase: RLSPhase,
    *parent_paths: str,
    **metadata,
) -> RLSManifestEntry:
    return RLSManifestEntry(
        model_label=model_label,
        db_table=db_table,
        category=RLSCategory.TENANT_PARENT,
        phase=phase,
        parent_paths=parent_paths,
        **metadata,
    )


def _mixed(
    model_label: str,
    db_table: str,
    *,
    organization_column: str | None = None,
    parent_paths: tuple[str, ...] = (),
    **metadata,
) -> RLSManifestEntry:
    return RLSManifestEntry(
        model_label=model_label,
        db_table=db_table,
        category=RLSCategory.TENANT_MIXED,
        phase=RLSPhase.RLS_1,
        organization_column=organization_column,
        parent_paths=parent_paths,
        rls1_covered=True,
        **metadata,
    )


def _rls1_direct(model_label: str, db_table: str, **metadata) -> RLSManifestEntry:
    return _direct(
        model_label,
        db_table,
        RLSPhase.RLS_1,
        rls1_covered=True,
        **metadata,
    )


def _rls1_parent(
    model_label: str,
    db_table: str,
    *parent_paths: str,
    **metadata,
) -> RLSManifestEntry:
    return _parent(
        model_label,
        db_table,
        RLSPhase.RLS_1,
        *parent_paths,
        rls1_covered=True,
        **metadata,
    )


RLS_MANIFEST = (
    # AI, catalog, assets, audit, jobs, and platforms: RLS-2A.
    _direct(
        "ai.AIRun",
        "ai_airun",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "ai.OrganizationAIProviderConfig",
        "ai_organizationaiproviderconfig",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    RLSManifestEntry(
        "ai.PromptVersion",
        "ai_promptversion",
        RLSCategory.GLOBAL_CONTEXT_READ,
        RLSPhase.RLS_2A,
        rationale="Published prompt templates are global runtime inputs, but must not be enumerable without a tenant context.",
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "assets.AssetProductLink",
        "assets_assetproductlink",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
    ),
    _direct(
        "assets.MaterialAsset",
        "assets_materialasset",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "assets.ProductEvidenceFact",
        "assets_productevidencefact",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "audit.ApprovalRecord",
        "audit_approvalrecord",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        contains_audit_data=True,
    ),
    _direct(
        "audit.AuditLog",
        "audit_auditlog",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        contains_audit_data=True,
    ),
    _direct(
        "catalog.Product",
        "catalog_product",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "catalog.ProductConceptLink",
        "catalog_productconceptlink",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "jobs.Job",
        "jobs_job",
        RLSPhase.RLS_2A,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _parent(
        "jobs.JobAttempt",
        "jobs_jobattempt",
        RLSPhase.RLS_2A,
        "job.organization",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "platforms.AccountConnectionSession",
        "platforms_accountconnectionsession",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
    ),
    _direct(
        "platforms.ConnectorCredential",
        "platforms_connectorcredential",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "platforms.EncryptedOAuthCredential",
        "platforms_encryptedoauthcredential",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "platforms.OAuthConnectionAttempt",
        "platforms_oauthconnectionattempt",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
    ),
    RLSManifestEntry(
        "platforms.Platform",
        "platforms_platform",
        RLSCategory.GLOBAL_CONTEXT_READ,
        RLSPhase.RLS_2A,
        rationale="The supported-platform dictionary is shared read-only runtime context and should require an established tenant.",
        background_task_access=True,
    ),
    RLSManifestEntry(
        "platforms.PlatformCapability",
        "platforms_platformcapability",
        RLSCategory.GLOBAL_CONTEXT_READ,
        RLSPhase.RLS_2A,
        rationale="Capabilities are shared dictionary rows owned by a global Platform and should require an established tenant.",
        background_task_access=True,
    ),
    _direct(
        "platforms.ProviderConnection",
        "platforms_providerconnection",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "platforms.ProviderConnectionEvent",
        "platforms_providerconnectionevent",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "platforms.SocialAccount",
        "platforms_socialaccount",
        RLSPhase.RLS_2A,
        contains_credentials=True,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    # Campaign, content, and publishing: RLS-2B.
    _direct(
        "campaigns.Campaign",
        "campaigns_campaign",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
    ),
    _direct(
        "campaigns.CampaignProduct",
        "campaigns_campaignproduct",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
    ),
    _direct(
        "campaigns.ContentBrief",
        "campaigns_contentbrief",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "campaigns.ContentBriefAsset",
        "campaigns_contentbriefasset",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "campaigns.ContentBriefConceptLink",
        "campaigns_contentbriefconceptlink",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "campaigns.ContentBriefPlatform",
        "campaigns_contentbriefplatform",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "campaigns.ContentBriefProduct",
        "campaigns_contentbriefproduct",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "content.ContentRecommendation",
        "content_contentrecommendation",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "content.ContentRecommendationOption",
        "content_contentrecommendationoption",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "content.MasterContent",
        "content_mastercontent",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "content.PlatformContent",
        "content_platformcontent",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "publishing.PostMetric",
        "publishing_postmetric",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "publishing.PublishAttempt",
        "publishing_publishattempt",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "publishing.PublishReconciliationAttempt",
        "publishing_publishreconciliationattempt",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "publishing.PublishTask",
        "publishing_publishtask",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "publishing.PublishedPost",
        "publishing_publishedpost",
        RLSPhase.RLS_2B,
        contains_customer_content=True,
        contains_publishing_data=True,
        public_entry_access=True,
        background_task_access=True,
    ),
    # Tracking moves to RLS-2C so its public short-code locator cannot be broken by RLS-2B.
    _direct(
        "tracking.ClickEvent",
        "tracking_clickevent",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        public_entry_access=True,
    ),
    _direct(
        "tracking.ShortLink",
        "tracking_shortlink",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        public_entry_access=True,
    ),
    _direct(
        "tracking.TrackingLink",
        "tracking_trackinglink",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        public_entry_access=True,
    ),
    # Growth and its public/scan boundaries: RLS-2C.
    _direct(
        "growth.AccountFunnelEvent",
        "growth_accountfunnelevent",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.AgentRun",
        "growth_agentrun",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.AgentRunStep",
        "growth_agentrunstep",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.CRMHandoff",
        "growth_crmhandoff",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.CandidateEnrichmentSnapshot",
        "growth_candidateenrichmentsnapshot",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.ChannelPackage",
        "growth_channelpackage",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.Contact",
        "growth_contact",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.CustomerServiceTurn",
        "growth_customerserviceturn",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.DiscoveryCandidate",
        "growth_discoverycandidate",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        public_entry_access=True,
        background_task_access=True,
    ),
    _direct(
        "growth.DiscoveryProfile",
        "growth_discoveryprofile",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.DiscoveryRun",
        "growth_discoveryrun",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.FieldProvenance",
        "growth_fieldprovenance",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
    ),
    _direct(
        "growth.FollowUp",
        "growth_followup",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.GoogleMapsDiscoveryConfig",
        "growth_googlemapsdiscoveryconfig",
        RLSPhase.RLS_2C,
        contains_credentials=True,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.GrowthEvent",
        "growth_growthevent",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.GrowthMission",
        "growth_growthmission",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.GrowthPublishBatch",
        "growth_growthpublishbatch",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.GrowthPublishItem",
        "growth_growthpublishitem",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.InboundLead",
        "growth_inboundlead",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        public_entry_access=True,
    ),
    _direct(
        "growth.InboundRfq",
        "growth_inboundrfq",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        public_entry_access=True,
    ),
    _direct(
        "growth.IntentSignal",
        "growth_intentsignal",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.LeadWebsiteVisit",
        "growth_leadwebsitevisit",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        public_entry_access=True,
    ),
    _direct(
        "growth.MarketCountryProfile",
        "growth_marketcountryprofile",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.MetricReceipt",
        "growth_metricreceipt",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_publishing_data=True,
    ),
    _direct(
        "growth.MissionEntityLink",
        "growth_missionentitylink",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.MissionPlan",
        "growth_missionplan",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _direct(
        "growth.OpportunityReview",
        "growth_opportunityreview",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.OutreachDraft",
        "growth_outreachdraft",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.OutreachMessage",
        "growth_outreachmessage",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.PromotionPlanApproval",
        "growth_promotionplanapproval",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
    ),
    _direct(
        "growth.ReactivationRecord",
        "growth_reactivationrecord",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.SalesDeal",
        "growth_salesdeal",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
    ),
    _direct(
        "growth.TargetAccount",
        "growth_targetaccount",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.TradeCompanyMatch",
        "growth_tradecompanymatch",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.TradeDatasetSnapshot",
        "growth_tradedatasetsnapshot",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        background_task_access=True,
    ),
    _direct(
        "growth.TradeSyncRun",
        "growth_tradesyncrun",
        RLSPhase.RLS_2C,
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    # Identity bootstrap/control plane.
    RLSManifestEntry(
        "identity.Membership",
        "identity_membership",
        RLSCategory.CONTROL_PLANE,
        RLSPhase.EXEMPT,
        organization_column="organization_id",
        rationale="Active Membership is the trusted server-side lookup that establishes the tenant before tenant-table access.",
        contains_customer_content=True,
    ),
    RLSManifestEntry(
        "identity.Organization",
        "identity_organization",
        RLSCategory.CONTROL_PLANE,
        RLSPhase.EXEMPT,
        rationale="Organization is the root control-plane identity and must be locatable before a tenant GUC exists.",
    ),
    _direct(
        "identity.PhaseAE2EOwnership",
        "identity_phaseae2eownership",
        RLSPhase.RLS_2C,
        contains_credentials=True,
        contains_audit_data=True,
    ),
    RLSManifestEntry(
        "identity.Role",
        "identity_role",
        RLSCategory.CONTROL_PLANE,
        RLSPhase.EXEMPT,
        rationale="Role permissions are required while resolving an active Membership before tenant context is established.",
    ),
    # Knowledge RLS-1 coverage plus the explicitly global graph lock.
    _rls1_direct(
        "knowledge.CompanyFact",
        "knowledge_companyfact",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _rls1_parent(
        "knowledge.CompanyFactEvidence",
        "knowledge_companyfactevidence",
        "company_fact.organization",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _rls1_direct(
        "knowledge.CompanyKnowledgeProfile",
        "knowledge_companyknowledgeprofile",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _rls1_parent(
        "knowledge.ICPProductLink",
        "knowledge_icpproductlink",
        "icp_profile.organization",
        contains_customer_content=True,
        background_task_access=True,
    ),
    _rls1_direct(
        "knowledge.ICPProfile",
        "knowledge_icpprofile",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _mixed(
        "knowledge.KnowledgeAlias",
        "knowledge_knowledgealias",
        organization_column="organization_id",
        contains_customer_content=True,
    ),
    _mixed(
        "knowledge.KnowledgeConcept",
        "knowledge_knowledgeconcept",
        organization_column="organization_id",
        contains_customer_content=True,
    ),
    _mixed(
        "knowledge.KnowledgeConceptEvidence",
        "knowledge_knowledgeconcept_evidence",
        parent_paths=("knowledgeconcept.organization",),
        contains_customer_content=True,
    ),
    _rls1_direct(
        "knowledge.KnowledgeContextSnapshot",
        "knowledge_knowledgecontextsnapshot",
        contains_customer_content=True,
        contains_audit_data=True,
        background_task_access=True,
    ),
    _mixed(
        "knowledge.KnowledgeEvidence",
        "knowledge_knowledgeevidence",
        organization_column="organization_id",
        contains_customer_content=True,
    ),
    RLSManifestEntry(
        "knowledge.KnowledgeGraphLock",
        "knowledge_knowledgegraphlock",
        RLSCategory.GLOBAL,
        RLSPhase.EXEMPT,
        rationale="This singleton only serializes global ontology graph mutations; it stores no tenant or customer data and must coordinate all tenants.",
    ),
    _mixed(
        "knowledge.KnowledgeRelation",
        "knowledge_knowledgerelation",
        organization_column="organization_id",
        contains_customer_content=True,
    ),
    _mixed(
        "knowledge.KnowledgeRelationEvidence",
        "knowledge_knowledgerelation_evidence",
        parent_paths=("knowledgerelation.organization",),
        contains_customer_content=True,
    ),
    _rls1_direct(
        "knowledge.WebsitePage",
        "knowledge_websitepage",
        contains_customer_content=True,
        contains_audit_data=True,
    ),
    _rls1_parent(
        "knowledge.WebsitePageConceptLink",
        "knowledge_websitepageconceptlink",
        "website_page.organization",
        contains_customer_content=True,
    ),
    _rls1_parent(
        "knowledge.WebsitePageProductLink",
        "knowledge_websitepageproductlink",
        "website_page.organization",
        contains_customer_content=True,
    ),
)


def iter_business_models(registry=django_apps):
    models = []
    for model in registry.get_models(include_auto_created=True):
        options = model._meta
        if (
            not options.managed
            or options.proxy
            or options.abstract
            or options.app_label in EXCLUDED_DJANGO_APP_LABELS
        ):
            continue
        models.append(model)
    return tuple(
        sorted(models, key=lambda model: (model._meta.label, model._meta.db_table))
    )


def _parent_path_error(model, path: str) -> str | None:
    current_model = model
    parts = path.split(".")
    if not path or any(not part for part in parts):
        return f"{model._meta.label}: invalid parent path {path!r}"
    for index, part in enumerate(parts):
        try:
            field = current_model._meta.get_field(part)
        except FieldDoesNotExist:
            return f"{model._meta.label}: invalid parent path {path!r} at {part!r}"
        if index == len(parts) - 1:
            related_model = getattr(field.remote_field, "model", None)
            related_label = (
                related_model._meta.label
                if getattr(related_model, "_meta", None)
                else None
            )
            if (
                field.column != "organization_id"
                or related_label != "identity.Organization"
            ):
                return f"{model._meta.label}: parent path {path!r} must end at identity.Organization"
            return None
        related_model = getattr(field.remote_field, "model", None)
        if related_model is None:
            return f"{model._meta.label}: parent path {path!r} crosses non-relation {part!r}"
        current_model = related_model
    return f"{model._meta.label}: invalid parent path {path!r}"


def audit_rls_coverage(
    *,
    entries: Iterable[RLSManifestEntry] | None = None,
    models: Iterable[type] | None = None,
) -> tuple[str, ...]:
    manifest = tuple(RLS_MANIFEST if entries is None else entries)
    business_models = tuple(iter_business_models() if models is None else models)
    errors: list[str] = []

    labels: dict[str, RLSManifestEntry] = {}
    tables: dict[str, RLSManifestEntry] = {}
    for entry in manifest:
        if entry.model_label in labels:
            errors.append(
                f"duplicate model classification: {entry.model_label} ({entry.db_table})"
            )
        else:
            labels[entry.model_label] = entry
        if entry.db_table in tables:
            errors.append(
                f"duplicate table classification: {entry.model_label} ({entry.db_table})"
            )
        else:
            tables[entry.db_table] = entry

    models_by_label = {model._meta.label: model for model in business_models}
    for label, model in models_by_label.items():
        entry = labels.get(label)
        if entry is None:
            errors.append(
                f"unclassified business table: {label} ({model._meta.db_table})"
            )
            continue
        if entry.db_table != model._meta.db_table:
            errors.append(
                f"table mismatch: {label} manifest={entry.db_table} registry={model._meta.db_table}"
            )
    for label, entry in labels.items():
        if label not in models_by_label:
            errors.append(
                f"manifest model/table does not exist: {label} ({entry.db_table})"
            )

    for entry in manifest:
        model = models_by_label.get(entry.model_label)
        if model is None:
            continue
        if entry.category in {RLSCategory.TENANT_DIRECT, RLSCategory.TENANT_MIXED}:
            if not entry.organization_column and not entry.parent_paths:
                errors.append(
                    f"{entry.model_label}: tenant classification lacks organization metadata"
                )
        if entry.category == RLSCategory.TENANT_PARENT and not entry.parent_paths:
            errors.append(f"{entry.model_label}: TENANT_PARENT requires parent_paths")
        if entry.organization_column:
            columns = {field.column for field in model._meta.concrete_fields}
            if entry.organization_column not in columns:
                errors.append(
                    f"{entry.model_label}: organization column {entry.organization_column!r} does not exist"
                )
        for path in entry.parent_paths:
            if error := _parent_path_error(model, path):
                errors.append(error)
        if (
            entry.category
            in {
                RLSCategory.GLOBAL_CONTEXT_READ,
                RLSCategory.CONTROL_PLANE,
                RLSCategory.GLOBAL,
            }
            and not entry.rationale.strip()
        ):
            errors.append(f"{entry.model_label}: {entry.category} requires a rationale")

    covered_tables = {entry.db_table for entry in manifest if entry.rls1_covered}
    if covered_tables != RLS1_TABLES:
        for table in sorted(RLS1_TABLES - covered_tables):
            errors.append(f"RLS-1 table is not marked covered: {table}")
        for table in sorted(covered_tables - RLS1_TABLES):
            errors.append(f"table is incorrectly marked RLS-1 covered: {table}")
    return tuple(sorted(set(errors)))


def assert_rls_coverage(
    *,
    entries: Iterable[RLSManifestEntry] | None = None,
    models: Iterable[type] | None = None,
) -> None:
    errors = audit_rls_coverage(entries=entries, models=models)
    if errors:
        raise RLSManifestError("\n".join(errors))
