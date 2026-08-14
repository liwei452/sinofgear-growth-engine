import uuid

from django.conf import settings
from django.db import models

from apps.identity.models import Organization


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

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="growth_unique_account_name")]


class Contact(OrganizationOwnedModel):
    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="contacts")
    full_name = models.CharField(max_length=255)
    role_title = models.CharField(max_length=160, blank=True)
    public_contact_path = models.URLField(blank=True)
    verification_status = models.CharField(max_length=32, default="PUBLIC_PATH")


class IntentSignal(OrganizationOwnedModel):
    account = models.ForeignKey(TargetAccount, on_delete=models.PROTECT, related_name="intent_signals")
    signal_type = models.CharField(max_length=64)
    source_label = models.CharField(max_length=255)
    source_url = models.URLField()
    evidence_text = models.TextField()
    confidence = models.PositiveSmallIntegerField(default=0)
    observed_at = models.DateTimeField(auto_now_add=True)
    is_demo = models.BooleanField(default=False)


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
