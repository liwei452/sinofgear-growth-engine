import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.common.models import OrganizationScopedModel


_content_write = ContextVar("content_service_write", default=False)


@contextmanager
def content_writes():
    token = _content_write.set(True)
    try:
        yield
    finally:
        _content_write.reset(token)


class ProtectedContentQuerySet(models.QuerySet):
    def _guard(self):
        if not _content_write.get():
            raise ValidationError("Content history may change only through services.")

    def update(self, **kwargs):
        self._guard()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        self._guard()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        self._guard()
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("Content history cannot be deleted.")


class ProtectedContentModel(OrganizationScopedModel):
    objects = models.Manager.from_queryset(ProtectedContentQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not _content_write.get():
            raise ValidationError("Content history may change only through services.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Content history cannot be deleted.")


def _validate_bounded_string_list(value, *, label, max_items=10, max_length=128):
    if not isinstance(value, list) or len(value) > max_items:
        raise ValidationError(f"{label} must be a bounded list.")
    if any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > max_length
        for item in value
    ):
        raise ValidationError(f"{label} entries must be bounded non-blank strings.")


class ContentRecommendation(OrganizationScopedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"
        ARCHIVED = "ARCHIVED", "Archived"

    class ProviderMode(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        FAKE_OFFLINE = "FAKE_OFFLINE", "Fake offline"
        CONFIGURED_AI = "CONFIGURED_AI", "Configured AI"

    job = models.OneToOneField(
        "jobs.Job", on_delete=models.PROTECT, related_name="content_recommendation"
    )
    input_snapshot = models.JSONField()
    provider_mode = models.CharField(
        max_length=32, choices=ProviderMode.choices, default=ProviderMode.NOT_STARTED
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    selected_option = models.ForeignKey(
        "ContentRecommendationOption",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="selected_by_recommendations",
    )
    selected_brief = models.OneToOneField(
        "campaigns.ContentBrief",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_content_recommendation",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_content_recommendations",
    )

    class Meta:
        ordering = ["-created_at", "-id"]

    def clean(self):
        super().clean()
        if self.organization_id and self.job_id:
            job = self.job if getattr(self, "job", None) is not None else None
            if job is None or job.organization_id != self.organization_id:
                raise ValidationError({"job": "Recommendation job organization must match."})
            if job.type != job.Type.CONTENT_RECOMMEND:
                raise ValidationError({"job": "Recommendation requires a content recommendation job."})
        if self.selected_option_id:
            selected = self.selected_option
            if (
                selected.organization_id != self.organization_id
                or selected.recommendation_id != self.id
            ):
                raise ValidationError(
                    {"selected_option": "Selected option must belong to this recommendation."}
                )


class ContentRecommendationOption(OrganizationScopedModel):
    recommendation = models.ForeignKey(
        ContentRecommendation, on_delete=models.PROTECT, related_name="options"
    )
    position = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(3)]
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="content_recommendation_options"
    )
    market_code = models.CharField(max_length=8)
    language = models.CharField(max_length=16)
    customer_profile = models.CharField(max_length=255)
    channel_codes = models.JSONField(default=list, blank=True)
    theme = models.CharField(max_length=500)
    rationale = models.TextField(max_length=2000)
    evidence = models.JSONField(default=list, blank=True)
    missing_information = models.JSONField(default=list, blank=True)
    selected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recommendation", "position"],
                name="content_recommendation_position_unique",
            ),
            models.UniqueConstraint(
                fields=[
                    "recommendation", "product", "market_code", "language",
                    "customer_profile", "theme",
                ],
                name="content_recommendation_option_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if self.organization_id and self.recommendation_id:
            if self.recommendation.organization_id != self.organization_id:
                raise ValidationError(
                    {"recommendation": "Recommendation organization must match."}
                )
        if self.organization_id and self.product_id:
            if self.product.organization_id != self.organization_id:
                raise ValidationError({"product": "Product organization must match."})
        self.market_code = self.market_code.strip().upper()
        self.language = self.language.strip().lower()
        self.customer_profile = self.customer_profile.strip()
        self.theme = self.theme.strip()
        self.rationale = self.rationale.strip()
        _validate_bounded_string_list(
            self.channel_codes, label="Channel codes", max_items=10, max_length=64
        )
        _validate_bounded_string_list(
            self.missing_information,
            label="Missing information",
            max_items=20,
            max_length=500,
        )
        if not isinstance(self.evidence, list) or len(self.evidence) > 100:
            raise ValidationError({"evidence": "Evidence must be a bounded list."})


class MasterContent(ProtectedContentModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ARCHIVED = "ARCHIVED", "Archived"

    brief = models.ForeignKey("campaigns.ContentBrief", on_delete=models.PROTECT, related_name="master_contents")
    brief_version = models.PositiveIntegerField()
    generation_job = models.ForeignKey("jobs.Job", on_delete=models.PROTECT, related_name="master_contents")
    ai_run = models.ForeignKey("ai.AIRun", on_delete=models.PROTECT, related_name="master_contents")
    lineage_id = models.UUIDField(default=uuid.uuid4, editable=False)
    previous_version = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_version")
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    provenance = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="master_content_versions")
    archived_from_status = models.CharField(max_length=16, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="archived_master_contents",
    )

    class Meta(ProtectedContentModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["lineage_id", "version"], name="content_master_lineage_version"),
            models.UniqueConstraint(fields=["generation_job"], condition=models.Q(version=1), name="content_master_initial_job"),
            models.UniqueConstraint(fields=["ai_run"], condition=models.Q(version=1), name="content_master_initial_run"),
        ]


class PlatformContent(ProtectedContentModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    master_content = models.ForeignKey(MasterContent, on_delete=models.PROTECT, related_name="platform_contents")
    master_version = models.PositiveIntegerField()
    platform = models.ForeignKey("platforms.Platform", on_delete=models.PROTECT, related_name="content_versions")
    lineage_id = models.UUIDField(default=uuid.uuid4, editable=False)
    previous_version = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_version")
    version = models.PositiveIntegerField(default=1)
    payload = models.JSONField()
    provenance = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="platform_content_versions")

    class Meta(ProtectedContentModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["lineage_id", "version"], name="content_platform_lineage_version"),
            models.UniqueConstraint(fields=["master_content", "platform", "version"], name="content_platform_master_target_version"),
        ]
