import uuid
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.identity.models import Organization


def default_gear_cpv_codes():
    return [
        "42140000", "42141000", "42141100", "42141200", "42141300",
        "42141400", "42141500", "42141600", "42141700", "42141800",
        "42142000", "42142100", "42142200",
    ]


class OrganizationOwnedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TargetAccount(OrganizationOwnedModel):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=96)
    industry = models.CharField(max_length=160, blank=True)
    employee_range = models.CharField(max_length=64, blank=True)
    website = models.URLField(blank=True)
    is_demo = models.BooleanField(default=False)
    source_identity = models.CharField(max_length=320, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_identity"],
                condition=~models.Q(source_identity=""),
                name="growth_unique_account_source_identity",
            ),
        ]


class Contact(OrganizationOwnedModel):
    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="contacts")
    full_name = models.CharField(max_length=255)
    role_title = models.CharField(max_length=160, blank=True)
    public_contact_path = models.URLField(blank=True)
    verification_status = models.CharField(max_length=32, default="PUBLIC_PATH")


class IntentSignal(OrganizationOwnedModel):
    SCORE_KEYS = {
        "icp_fit", "intent_strength", "recency", "role_relevance",
        "evidence_coverage", "risk_penalty",
    }

    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="intent_signals")
    signal_type = models.CharField(max_length=64)
    source_label = models.CharField(max_length=255)
    source_url = models.URLField()
    evidence_text = models.TextField()
    confidence = models.PositiveSmallIntegerField(default=0)
    observed_at = models.DateTimeField(auto_now_add=True)
    is_demo = models.BooleanField(default=False)
    collection_method = models.CharField(max_length=32, default="DEMO_FIXTURE")
    content_hash = models.CharField(max_length=64, blank=True)
    score_breakdown = models.JSONField(default=dict)
    scoring_rule_version = models.CharField(max_length=64, default="opportunity-v1")
    uncertainty_notes = models.JSONField(default=list)
    evidence_envelope = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "content_hash"],
                condition=~models.Q(content_hash=""),
                name="growth_unique_signal_evidence_hash",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.content_hash and re.fullmatch(r"[0-9a-f]{64}", self.content_hash) is None:
            errors["content_hash"] = "Evidence hash must be a lowercase SHA-256 value."

        breakdown = self.score_breakdown
        if breakdown:
            if not isinstance(breakdown, dict) or set(breakdown) != self.SCORE_KEYS:
                errors["score_breakdown"] = "Score breakdown must contain the six opportunity-v1 keys."
            elif any(type(value) is not int or not 0 <= value <= 100 for value in breakdown.values()):
                errors["score_breakdown"] = "Score components must be integers from 0 to 100."
            else:
                total = sum(breakdown[key] for key in self.SCORE_KEYS - {"risk_penalty"})
                total -= breakdown["risk_penalty"]
                if total != self.confidence:
                    errors["score_breakdown"] = "Score component total must match confidence."

        if not isinstance(self.uncertainty_notes, list) or any(
            not isinstance(note, str) or not note.strip() for note in self.uncertainty_notes
        ):
            errors["uncertainty_notes"] = "Uncertainty notes must be a list of non-empty strings."
        if errors:
            raise ValidationError(errors)


class InboundLead(OrganizationOwnedModel):
    class Route(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACQUISITION = "ACQUISITION", "Acquisition"
        CUSTOMER_SERVICE = "CUSTOMER_SERVICE", "Customer service"
        MANUAL_REVIEW = "MANUAL_REVIEW", "Manual review"

    account = models.ForeignKey(TargetAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="inbound_leads")
    source_label = models.CharField(max_length=255)
    status = models.CharField(max_length=32, default="NEW")
    route = models.CharField(max_length=24, choices=Route.choices, default=Route.PENDING)
    route_reason = models.CharField(max_length=500, blank=True)
    routed_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)


class InboundRfq(OrganizationOwnedModel):
    lead = models.ForeignKey(
        InboundLead,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rfqs",
    )
    account = models.ForeignKey(
        TargetAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inbound_rfqs",
    )
    company_name = models.CharField(max_length=255)
    country = models.CharField(max_length=96, blank=True)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    industry = models.CharField(max_length=160, blank=True)
    product_interest = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    file_names = models.JSONField(default=list)
    need_slug = models.CharField(max_length=32, blank=True)
    landing_page = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=24, default="NEW")
    external_request_id = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "external_request_id"],
                condition=~models.Q(external_request_id=""),
                name="growth_unique_rfq_request_id",
            ),
        ]


class CustomerServiceTurn(OrganizationOwnedModel):
    class Decision(models.TextChoices):
        AUTO_REPLY = "AUTO_REPLY", "Auto reply"
        HUMAN_ESCALATION = "HUMAN_ESCALATION", "Human escalation"

    lead = models.ForeignKey(
        InboundLead,
        on_delete=models.PROTECT,
        related_name="customer_service_turns",
    )
    rfq = models.ForeignKey(
        InboundRfq,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_service_turns",
    )
    decision = models.CharField(max_length=24, choices=Decision.choices)
    draft_reply = models.TextField(blank=True)
    reasoning = models.TextField(blank=True)
    evidence = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "rfq"],
                name="growth_unique_customer_service_rfq",
            ),
        ]


class GrowthEvent(OrganizationOwnedModel):
    event_type = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)

    class Meta:
        ordering = ["occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="growth_unique_event_key",
            ),
        ]


class FollowUp(OrganizationOwnedModel):
    class Stage(models.TextChoices):
        DISCOVERED = "DISCOVERED", "Discovered"
        QUALIFIED = "QUALIFIED", "Qualified"
        ENRICHED = "ENRICHED", "Enriched"
        CONTACT_FOUND = "CONTACT_FOUND", "Contact found"
        EMAIL_VERIFIED = "EMAIL_VERIFIED", "Email verified"
        OUTREACH_READY = "OUTREACH_READY", "Outreach ready"
        EMAIL_1_SENT = "EMAIL_1_SENT", "Email 1 sent"
        OPENED = "OPENED", "Opened"
        SITE_VISITED = "SITE_VISITED", "Site visited"
        FOLLOW_UP_1 = "FOLLOW_UP_1", "Follow up 1"
        REPLIED = "REPLIED", "Replied"
        BOUNCED = "BOUNCED", "Bounced"
        UNSUBSCRIBED = "UNSUBSCRIBED", "Unsubscribed"
        RFQ = "RFQ", "RFQ"
        QUOTED = "QUOTED", "Quoted"
        WON = "WON", "Won"
        LOST = "LOST", "Lost"

    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="follow_ups")
    status = models.CharField(max_length=32, default="OPEN")
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.QUALIFIED)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "account"], name="growth_one_follow_up_per_account")]


class OutreachDraft(OrganizationOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        APPROVED = "APPROVED", "Approved"

    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="outreach_drafts")
    english_draft = models.TextField()
    chinese_explanation = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)


class OutreachMessage(OrganizationOwnedModel):
    class Status(models.TextChoices):
        SENT = "SENT", "Sent"
        REPLIED = "REPLIED", "Replied"
        BOUNCED = "BOUNCED", "Bounced"
        UNSUBSCRIBED = "UNSUBSCRIBED", "Unsubscribed"

    account = models.ForeignKey(
        TargetAccount,
        on_delete=models.PROTECT,
        related_name="outreach_messages",
    )
    draft = models.ForeignKey(
        OutreachDraft,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outreach_messages",
    )
    provider = models.CharField(max_length=64)
    provider_message_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SENT)
    payload = models.JSONField(default=dict)
    sent_at = models.DateTimeField(null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ReactivationRecord(OrganizationOwnedModel):
    class RelationshipSource(models.TextChoices):
        EXISTING_CUSTOMER = "EXISTING_CUSTOMER", "Existing customer"
        PAST_INQUIRY = "PAST_INQUIRY", "Past inquiry"
        TRADE_SHOW = "TRADE_SHOW", "Trade show"
        OWNED_CRM = "OWNED_CRM", "Owned CRM"

    class Tier(models.TextChoices):
        STRATEGIC = "STRATEGIC", "Strategic"
        NURTURE = "NURTURE", "Nurture"
        OBSERVATION = "OBSERVATION", "Observation"

    class Status(models.TextChoices):
        SELECTED = "SELECTED", "Selected"
        DRAFTED = "DRAFTED", "Drafted"
        APPROVED = "APPROVED", "Approved"

    account = models.ForeignKey(
        TargetAccount, on_delete=models.PROTECT, related_name="reactivations",
    )
    relationship_source = models.CharField(max_length=32, choices=RelationshipSource.choices)
    last_interacted_at = models.DateTimeField()
    interaction_summary = models.TextField()
    relationship_confirmed = models.BooleanField(default=False)
    tier = models.CharField(max_length=16, choices=Tier.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SELECTED)
    draft = models.ForeignKey(
        OutreachDraft, null=True, blank=True, on_delete=models.PROTECT,
        related_name="reactivation_records",
    )
    selected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="selected_reactivations",
    )
    is_demo = models.BooleanField(default=False)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "account"],
                name="growth_one_reactivation_per_account",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Reactivation history cannot be deleted.")


class AccountFunnelEvent(OrganizationOwnedModel):
    class EventType(models.TextChoices):
        REACTIVATION_SELECTED = "REACTIVATION_SELECTED", "Reactivation selected"
        REACTIVATION_DRAFTED = "REACTIVATION_DRAFTED", "Reactivation drafted"
        REACTIVATION_APPROVED = "REACTIVATION_APPROVED", "Reactivation approved"

    account = models.ForeignKey(
        TargetAccount, on_delete=models.PROTECT, related_name="funnel_events",
    )
    reactivation = models.ForeignKey(
        ReactivationRecord, on_delete=models.PROTECT, related_name="events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="growth_account_funnel_events",
    )
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["reactivation", "event_type"],
                name="growth_one_reactivation_event_type",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Account funnel history cannot be deleted.")


class OpportunityReview(OrganizationOwnedModel):
    class Decision(models.TextChoices):
        PRIORITIZE = "PRIORITIZE", "Prioritize"
        OBSERVE = "OBSERVE", "Observe"
        PROCESSED = "PROCESSED", "Processed"

    account = models.ForeignKey(
        TargetAccount, on_delete=models.PROTECT, related_name="opportunity_reviews",
    )
    signal = models.ForeignKey(
        IntentSignal, on_delete=models.PROTECT, related_name="opportunity_reviews",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=255)
    original_confidence = models.PositiveSmallIntegerField()
    original_score_breakdown = models.JSONField(default=dict)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="growth_opportunity_reviews",
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def delete(self, *args, **kwargs):
        raise ValueError("Opportunity review history cannot be deleted.")


class CRMHandoff(OrganizationOwnedModel):
    review = models.ForeignKey(
        OpportunityReview, on_delete=models.PROTECT, related_name="crm_handoffs",
    )
    draft = models.ForeignKey(
        OutreachDraft, on_delete=models.PROTECT, related_name="crm_handoffs",
    )
    connector = models.CharField(max_length=32, default="MOCK_CRM")
    status = models.CharField(max_length=24, default="RECORDED")
    payload_snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="growth_crm_handoffs",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "review"],
                name="growth_one_crm_handoff_per_review",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("CRM handoff history cannot be deleted.")


class ChannelPackage(OrganizationOwnedModel):
    account = models.ForeignKey(TargetAccount, null=True, blank=True, on_delete=models.PROTECT)
    source_platform_content = models.OneToOneField(
        "content.PlatformContent",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="growth_channel_package",
    )
    channel = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default="AWAITING_REVIEW")
    is_demo = models.BooleanField(default=False)


class GrowthPublishBatch(OrganizationOwnedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        PARTIAL_SUCCESS = "PARTIAL_SUCCESS", "Partial success"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED", "Configuration required"

    idempotency_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=32, choices=Status.choices)
    is_demo = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="growth_publish_batches",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="growth_unique_publish_batch_key",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Publishing history cannot be deleted.")


class GrowthPublishItem(OrganizationOwnedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        DELEGATED = "DELEGATED", "Delegated"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    batch = models.ForeignKey(
        GrowthPublishBatch, on_delete=models.PROTECT, related_name="items",
    )
    channel_package = models.ForeignKey(
        ChannelPackage, on_delete=models.PROTECT, related_name="publish_items",
    )
    publish_task = models.ForeignKey(
        "publishing.PublishTask",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="growth_publish_items",
    )
    social_account = models.ForeignKey(
        "platforms.SocialAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="growth_publish_items",
    )
    channel = models.CharField(max_length=32)
    payload_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices)
    attempt_number = models.PositiveIntegerField(default=0)
    external_post_id = models.CharField(max_length=255, blank=True)
    external_post_url = models.URLField(blank=True)
    last_error = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["channel", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "channel"],
                name="growth_unique_publish_batch_channel",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Publishing history cannot be deleted.")


class MetricReceipt(OrganizationOwnedModel):
    channel = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    is_demo = models.BooleanField(default=False)


class FieldProvenance(OrganizationOwnedModel):
    field_name = models.CharField(max_length=160)
    field_value = models.TextField()
    source_label = models.CharField(max_length=255)
    verification_status = models.CharField(max_length=32)
    source_cost_micros = models.PositiveBigIntegerField(default=0)
    is_demo = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "field_name"], name="growth_unique_fact_field")]


class MarketCountryProfile(OrganizationOwnedModel):
    class Status(models.TextChoices):
        OBSERVATION_POOL = "OBSERVATION_POOL", "Observation pool"
        DATA_VALIDATION = "DATA_VALIDATION", "Data validation"
        SMALL_PILOT = "SMALL_PILOT", "Small pilot"
        ACTIVE_MARKET = "ACTIVE_MARKET", "Active market"
        PAUSED = "PAUSED", "Paused"

    country_code = models.CharField(max_length=3)
    country_label = models.CharField(max_length=96)
    region = models.CharField(max_length=32, default="OTHER")
    path_family = models.CharField(max_length=32, default="MIXED_ACQUISITION")
    suitable_industries = models.JSONField(default=list)
    data_availability_label = models.CharField(max_length=64, default="待验证")
    evidence_note = models.CharField(max_length=255, default="研究配置，尚无实时数据")
    recommended_action = models.CharField(max_length=160, default="先导入许可名单或公开线索")
    is_demo = models.BooleanField(default=True)
    is_watched = models.BooleanField(default=False)
    status = models.CharField(max_length=24, choices=Status.choices)
    route = models.CharField(max_length=48)
    route_label = models.CharField(max_length=128)
    recommended_wave = models.CharField(max_length=64)
    priority_order = models.PositiveSmallIntegerField()
    source_types = models.JSONField(default=list)
    last_researched_at = models.DateField()
    scores = models.JSONField(default=dict)
    sample_quality = models.JSONField(default=dict)
    recommendation_reasons = models.JSONField(default=list)
    hold_reasons = models.JSONField(default=list)

    class Meta:
        ordering = ["priority_order", "country_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "country_code"],
                name="growth_unique_market_country",
            ),
        ]


class DiscoveryCandidate(OrganizationOwnedModel):
    class Status(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "Pending review"
        ACCEPTED = "ACCEPTED", "Accepted"
        DISMISSED = "DISMISSED", "Dismissed"

    company_name = models.CharField(max_length=255)
    country = models.CharField(max_length=96)
    website = models.URLField(blank=True)
    industry = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING_REVIEW,
    )
    import_format = models.CharField(max_length=16)
    source_governance = models.JSONField(default=dict)
    raw_record = models.JSONField(default=dict)
    record_hash = models.CharField(max_length=64)
    is_demo = models.BooleanField(default=False)
    score = models.PositiveSmallIntegerField(default=0)
    grade = models.CharField(max_length=1, default="C")
    score_breakdown = models.JSONField(default=dict)
    intent_score = models.PositiveSmallIntegerField(default=0)
    intent_breakdown = models.JSONField(default=dict)
    review_note = models.CharField(max_length=255, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="growth_discovery_candidate_reviews",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["organization", "status", "-created_at"],
                name="growth_cand_org_status_idx",
            ),
            models.Index(
                fields=["organization", "-created_at"],
                name="growth_cand_org_created_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "record_hash"],
                name="growth_unique_discovery_candidate_hash",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Discovery candidate history cannot be deleted.")


class CandidateEnrichmentSnapshot(OrganizationOwnedModel):
    candidate = models.OneToOneField(
        DiscoveryCandidate,
        on_delete=models.PROTECT,
        related_name="enrichment_snapshot",
    )
    target_account = models.OneToOneField(
        TargetAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="candidate_enrichment_snapshot",
    )
    mode = models.CharField(max_length=24, default="FAKE_PREVIEW")
    facts = models.JSONField(default=list)
    public_contact_paths = models.JSONField(default=list)
    uncertainties = models.JSONField(default=list)
    evidence_envelope = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at", "-id"]

    def delete(self, *args, **kwargs):
        raise ValueError("Candidate enrichment history cannot be deleted.")


class DiscoveryProfile(OrganizationOwnedModel):
    organization = models.OneToOneField(
        Organization, on_delete=models.PROTECT, related_name="growth_discovery_profile",
    )
    enabled = models.BooleanField(default=True)
    source_code = models.CharField(max_length=32, default="OFFICIAL_PROCUREMENT")
    cpv_codes = models.JSONField(default=default_gear_cpv_codes)
    result_limit = models.PositiveSmallIntegerField(default=20)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_succeeded_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True)


class DiscoveryRun(OrganizationOwnedModel):
    class Trigger(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SCHEDULED = "SCHEDULED", "Scheduled"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    profile = models.ForeignKey(
        DiscoveryProfile, on_delete=models.PROTECT, related_name="runs",
    )
    source_code = models.CharField(max_length=32)
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    query_snapshot = models.JSONField(default=dict)
    capability_snapshot = models.JSONField(default=dict)
    fetched_count = models.PositiveIntegerField(default=0)
    created_account_count = models.PositiveIntegerField(default=0)
    created_signal_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def delete(self, *args, **kwargs):
        raise ValueError("Discovery run history cannot be deleted.")


class TradeSyncRun(OrganizationOwnedModel):
    class Trigger(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SCHEDULED = "SCHEDULED", "Scheduled"

    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="growth_trade_sync_runs",
    )
    source_code = models.CharField(max_length=32)
    trigger = models.CharField(max_length=16, choices=Trigger.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    query_snapshot = models.JSONField(default=dict)
    query_hash = models.CharField(max_length=64)
    capability_snapshot = models.JSONField(default=dict)
    fetched_count = models.PositiveIntegerField(default=0)
    created_snapshot_count = models.PositiveIntegerField(default=0)
    reused_snapshot_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def delete(self, *args, **kwargs):
        raise ValueError("Trade sync history cannot be deleted.")


class TradeDatasetSnapshot(OrganizationOwnedModel):
    first_seen_run = models.ForeignKey(
        TradeSyncRun,
        on_delete=models.PROTECT,
        related_name="first_seen_snapshots",
    )
    reporter_code = models.CharField(max_length=3)
    reporter_name = models.CharField(max_length=200, blank=True)
    partner_code = models.CharField(max_length=3)
    partner_name = models.CharField(max_length=200, blank=True)
    flow = models.CharField(max_length=2)
    flow_name = models.CharField(max_length=40, blank=True)
    hs_code = models.CharField(max_length=6)
    period = models.CharField(max_length=6)
    frequency = models.CharField(max_length=8)
    trade_value_usd = models.DecimalField(max_digits=24, decimal_places=2)
    quantity = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    quantity_unit = models.CharField(max_length=40, blank=True)
    source_url = models.URLField(max_length=1000)
    source_dataset = models.CharField(max_length=80)
    dataset_version = models.CharField(max_length=100, blank=True)
    observed_at = models.DateField()
    fetched_at = models.DateTimeField()
    freshness_days = models.PositiveIntegerField()
    record_hash = models.CharField(max_length=64)
    provenance = models.JSONField(default=dict)
    is_demo = models.BooleanField(default=False)

    class Meta:
        ordering = ["-observed_at", "hs_code", "partner_code", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "record_hash"],
                name="growth_unique_trade_snapshot_hash",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValueError("Trade dataset snapshot history cannot be deleted.")


DEFAULT_MAPS_CITIES = (
    {"name": "Ho Chi Minh", "country_code": "VN"},
    {"name": "Hanoi", "country_code": "VN"},
    {"name": "Haiphong", "country_code": "VN"},
    {"name": "Binh Duong", "country_code": "VN"},
    {"name": "Dong Nai", "country_code": "VN"},
    {"name": "Jakarta", "country_code": "ID"},
    {"name": "Surabaya", "country_code": "ID"},
    {"name": "Bandung", "country_code": "ID"},
    {"name": "Manila", "country_code": "PH"},
    {"name": "Cebu", "country_code": "PH"},
    {"name": "Johannesburg", "country_code": "ZA"},
    {"name": "Durban", "country_code": "ZA"},
    {"name": "Cape Town", "country_code": "ZA"},
)
DEFAULT_MAPS_KEYWORDS = (
    "mining equipment",
    "conveyor",
    "crusher",
    "industrial machinery",
    "gearbox repair",
    "cement equipment",
    "agricultural machinery",
    "packaging machinery",
)


def default_maps_cities():
    return [dict(city) for city in DEFAULT_MAPS_CITIES]


def default_maps_keywords():
    return list(DEFAULT_MAPS_KEYWORDS)


class GoogleMapsDiscoveryConfig(OrganizationOwnedModel):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="google_maps_discovery_config",
    )
    enabled = models.BooleanField(default=False)
    api_key_ciphertext = models.TextField(blank=True)
    api_key_key_version = models.PositiveSmallIntegerField(default=1)
    cities = models.JSONField(default=default_maps_cities)
    keywords = models.JSONField(default=default_maps_keywords)
    radius_km = models.PositiveSmallIntegerField(default=50)
    daily_quota = models.PositiveSmallIntegerField(default=500)
    schedule_time = models.CharField(max_length=5, default="02:00")
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_succeeded_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True)

    def delete(self, *args, **kwargs):
        raise ValueError("Google Maps discovery config cannot be deleted.")


class PromotionPlanApproval(OrganizationOwnedModel):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.PROTECT,
        related_name="promotion_plan_approval",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="growth_promotion_plan_approvals",
    )
    plan_snapshot = models.JSONField(default=dict)
    version = models.PositiveSmallIntegerField(default=0)

    def delete(self, *args, **kwargs):
        raise ValueError("Promotion plan approval history cannot be deleted.")


class SalesDeal(OrganizationOwnedModel):
    class Stage(models.TextChoices):
        QUOTE_CREATED = "QUOTE_CREATED", "Quote created"
        QUOTE_SENT = "QUOTE_SENT", "Quote sent"
        NEGOTIATING = "NEGOTIATING", "Negotiating"
        WON = "WON", "Won"
        LOST = "LOST", "Lost"
        NURTURE = "NURTURE", "Nurture"

    account = models.ForeignKey(
        TargetAccount,
        on_delete=models.PROTECT,
        related_name="sales_deals",
    )
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.QUOTE_CREATED)
    quote_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    won_at = models.DateTimeField(null=True, blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)

    def delete(self, *args, **kwargs):
        raise ValueError("Sales deal history cannot be deleted.")


class TradeCompanyMatch(OrganizationOwnedModel):
    importer_name = models.CharField(max_length=255)
    country_code = models.CharField(max_length=3)
    account = models.ForeignKey(
        TargetAccount,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="trade_company_matches",
    )
    method = models.CharField(max_length=24, default="NO_MATCH")
    confidence = models.FloatField(default=0.0)

    def delete(self, *args, **kwargs):
        raise ValueError("Trade company match history cannot be deleted.")


class LeadWebsiteVisit(OrganizationOwnedModel):
    candidate = models.ForeignKey(
        DiscoveryCandidate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="website_visits",
    )
    path = models.CharField(max_length=500)
    utm_source = models.CharField(max_length=64, blank=True)
    utm_campaign = models.CharField(max_length=128, blank=True)
    session_id = models.CharField(max_length=128, blank=True)
    visited_at = models.DateTimeField(default=timezone.now)


class AgentRun(OrganizationOwnedModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        WAITING_APPROVAL = "WAITING_APPROVAL", "Waiting approval"
        COMPLETED = "COMPLETED", "Completed"
        BUDGET_EXCEEDED = "BUDGET_EXCEEDED", "Budget exceeded"
        FAILED = "FAILED", "Failed"
        REJECTED = "REJECTED", "Rejected"

    idempotency_key = models.CharField(max_length=128)
    goal = models.CharField(max_length=500)
    agent_type = models.CharField(max_length=32, blank=True)
    resume_args = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.RUNNING)
    terminal_reason = models.CharField(max_length=500, blank=True)
    max_steps = models.PositiveSmallIntegerField(default=20)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiated_agent_runs",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_agent_runs",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_agent_runs",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    approval_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="growth_unique_agent_run_key",
            ),
        ]


class AgentRunStep(OrganizationOwnedModel):
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.PROTECT,
        related_name="steps",
    )
    index = models.PositiveSmallIntegerField()
    tool_name = models.CharField(max_length=160, blank=True)
    args = models.JSONField(default=dict)
    outcome = models.CharField(max_length=32)
    output = models.JSONField(null=True, blank=True)
    error = models.CharField(max_length=1000, blank=True)
    reasoning = models.TextField(blank=True)
    approval_token = models.CharField(max_length=64, blank=True)
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="executed_agent_run_steps",
    )

    class Meta:
        ordering = ["index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "index"],
                name="growth_unique_agent_run_step_index",
            ),
        ]
