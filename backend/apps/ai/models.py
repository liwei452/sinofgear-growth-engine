import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


_audit_write: ContextVar[bool] = ContextVar("ai_audit_write", default=False)


class OrganizationAIProviderConfig(models.Model):
    organization = models.OneToOneField(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="ai_provider_config",
    )
    provider = models.CharField(max_length=32, default="deepseek")
    model = models.CharField(max_length=64, default="deepseek-chat")
    encrypted_api_key = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)
    daily_budget_micros = models.PositiveBigIntegerField(null=True, blank=True)
    daily_spent_micros = models.PositiveBigIntegerField(default=0)
    daily_reserved_micros = models.PositiveBigIntegerField(default=0)
    spent_on = models.DateField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization_id"]


@contextmanager
def ai_audit_writes():
    token = _audit_write.set(True)
    try:
        yield
    finally:
        _audit_write.reset(token)


class AuditQuerySet(models.QuerySet):
    @staticmethod
    def _guard():
        if not _audit_write.get():
            raise ValidationError("AI audit records may change only through services.")

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
        raise ValidationError("AI audit records cannot be deleted.")


class AuditManager(models.Manager.from_queryset(AuditQuerySet)):
    pass


class AuditModel(models.Model):
    objects = AuditManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _audit_write.get():
            raise ValidationError("AI audit records may change only through services.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AI audit records cannot be deleted.")


class PromptVersion(AuditModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField(max_length=64)
    code = models.CharField(max_length=96)
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    template = models.TextField()
    output_schema = models.JSONField()
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_prompt_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["purpose", "-version", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "version"], name="ai_unique_prompt_purpose_version"
            )
        ]


class AIRun(AuditModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, related_name="ai_runs"
    )
    job = models.ForeignKey("jobs.Job", on_delete=models.PROTECT, related_name="ai_runs")
    job_attempt = models.PositiveSmallIntegerField()
    prompt_version = models.ForeignKey(
        PromptVersion, on_delete=models.PROTECT, related_name="ai_runs"
    )
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    input_snapshot = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices)
    output_json = models.JSONField(null=True, blank=True)
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    provider_metadata = models.JSONField(default=dict)
    error = models.JSONField(null=True, blank=True)
    human_correction = models.JSONField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_ai_runs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "job_attempt"], name="ai_unique_run_per_job_attempt"
            )
        ]
