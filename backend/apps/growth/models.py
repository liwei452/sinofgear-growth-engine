import uuid
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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
    account = models.ForeignKey(TargetAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="inbound_leads")
    source_label = models.CharField(max_length=255)
    status = models.CharField(max_length=32, default="NEW")
    is_demo = models.BooleanField(default=False)


class FollowUp(OrganizationOwnedModel):
    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="follow_ups")
    status = models.CharField(max_length=32, default="OPEN")

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
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    batch = models.ForeignKey(
        GrowthPublishBatch, on_delete=models.PROTECT, related_name="items",
    )
    channel_package = models.ForeignKey(
        ChannelPackage, on_delete=models.PROTECT, related_name="publish_items",
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
