import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


_audit_write: ContextVar[bool] = ContextVar("ai_audit_write", default=False)


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
    transport_retry_count = models.PositiveSmallIntegerField(default=0)
    repair_attempted = models.BooleanField(default=False)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    next_call_generation = models.PositiveSmallIntegerField(default=1)
    next_call_phase = models.CharField(max_length=12, default="NORMAL")
    retry_dispatch_token = models.UUIDField(null=True, blank=True)
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


class AIProviderConfiguration(models.Model):
    class ConnectionState(models.TextChoices):
        NOT_CONFIGURED = "NOT_CONFIGURED", "Not configured"
        CONNECTED = "CONNECTED", "Connected"
        NEEDS_RECONNECT = "NEEDS_RECONNECT", "Needs reconnect"
        CONFIGURING = "CONFIGURING", "Configuring"

    organization = models.OneToOneField(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="ai_provider_configuration",
    )
    provider_code = models.CharField(max_length=32, default="deepseek", editable=False)
    connection_state = models.CharField(
        max_length=24,
        choices=ConnectionState.choices,
        default=ConnectionState.NOT_CONFIGURED,
    )
    key_suffix = models.CharField(max_length=4, blank=True)
    credential_revision = models.PositiveIntegerField(default=0)
    operation_revision = models.PositiveBigIntegerField(default=0)
    operation_token = models.UUIDField(null=True, blank=True, editable=False)
    operation_started_at = models.DateTimeField(null=True, blank=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_tested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tested_ai_provider_configurations",
    )
    daily_budget_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100000)],
    )
    flash_max_output_tokens = models.PositiveIntegerField(
        default=1200, validators=[MinValueValidator(64), MaxValueValidator(65536)]
    )
    pro_max_output_tokens = models.PositiveIntegerField(
        default=2400, validators=[MinValueValidator(64), MaxValueValidator(65536)]
    )
    timeout_seconds = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(1), MaxValueValidator(300)]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["organization_id"]

    def clean(self):
        super().clean()
        connected = self.connection_state == self.ConnectionState.CONNECTED
        if connected and re.fullmatch(r"[A-Za-z0-9_-]{4}", self.key_suffix) is None:
            raise ValidationError({"key_suffix": "Connected credentials require a 4-character suffix."})
        if not connected and self.key_suffix:
            raise ValidationError({"key_suffix": "Unconfigured credentials cannot have a suffix."})
        active = self.connection_state == self.ConnectionState.CONFIGURING
        if active != bool(self.operation_token and self.operation_started_at):
            raise ValidationError({"operation_token": "Configuring state requires an active operation."})


class ImmutableIntentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("AI execution intents are immutable.")

    def delete(self):
        raise ValidationError("AI execution intents cannot be deleted.")


class ImmutableIntentManager(models.Manager.from_queryset(ImmutableIntentQuerySet)):
    pass


class AIExecutionIntent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField(
        "jobs.Job", on_delete=models.PROTECT, related_name="ai_execution_intent"
    )
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, related_name="ai_execution_intents"
    )
    provider = models.CharField(max_length=64)
    model = models.CharField(max_length=128)
    thinking_enabled = models.BooleanField(default=False)
    policy_code = models.CharField(max_length=64)
    policy_version = models.PositiveIntegerField()
    override_reason = models.CharField(max_length=96, blank=True)
    max_output_tokens = models.PositiveIntegerField()
    timeout_seconds = models.PositiveSmallIntegerField()
    estimated_input_tokens = models.PositiveIntegerField()
    reserved_cost_usd = models.DecimalField(max_digits=12, decimal_places=6)
    provider_prompt = models.TextField(blank=True)
    provider_schema = models.JSONField(default=dict)
    provider_input_sha256 = models.CharField(max_length=64, blank=True)
    prompt_purpose = models.CharField(max_length=64, blank=True)
    prompt_version_id_snapshot = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_ai_execution_intents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ImmutableIntentManager()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reserved_cost_usd__gte=0),
                name="ai_intent_reserved_cost_nonnegative",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("AI execution intents are immutable.")
        if self.provider_prompt and self.provider_schema and not self.provider_input_sha256:
            import hashlib
            import json

            encoded = json.dumps(
                {"prompt": self.provider_prompt, "schema": self.provider_schema},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            self.provider_input_sha256 = hashlib.sha256(encoded).hexdigest()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AI execution intents cannot be deleted.")


class AIUsageDay(models.Model):
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, related_name="ai_usage_days"
    )
    usage_date = models.DateField()
    reserved_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    actual_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-usage_date", "organization_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "usage_date"], name="ai_unique_usage_day"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_usd__gte=0),
                name="ai_usage_day_reserved_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_usd__gte=0),
                name="ai_usage_day_actual_nonnegative",
            ),
        ]


class AIUsageAttempt(models.Model):
    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Reserved"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.OneToOneField(
        AIRun, on_delete=models.PROTECT, related_name="usage_attempt"
    )
    intent = models.ForeignKey(
        AIExecutionIntent, on_delete=models.PROTECT, related_name="usage_attempts"
    )
    usage_day = models.ForeignKey(
        AIUsageDay, on_delete=models.PROTECT, related_name="attempts"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RESERVED
    )
    reserved_usd = models.DecimalField(max_digits=12, decimal_places=6)
    additional_reserved_usd = models.DecimalField(
        max_digits=12, decimal_places=6, default=0
    )
    actual_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_hit_tokens = models.PositiveIntegerField(default=0)
    pricing_code = models.CharField(max_length=64, blank=True)
    pricing_version = models.PositiveIntegerField(null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reserved_usd__gte=0),
                name="ai_usage_attempt_reserved_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(actual_usd__gte=0),
                name="ai_usage_attempt_actual_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(additional_reserved_usd__gte=0),
                name="ai_usage_attempt_extra_reserved_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="RESERVED", reconciled_at__isnull=True)
                    | models.Q(
                        status__in=["SUCCEEDED", "FAILED", "CANCELED"],
                        reconciled_at__isnull=False,
                    )
                ),
                name="ai_usage_attempt_reconcile_state",
            ),
        ]


class AIProviderCall(models.Model):
    class Phase(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        REPAIR = "REPAIR", "Repair"
    class Status(models.TextChoices):
        RESERVED = "RESERVED", "Reserved"
        CALLING = "CALLING", "Calling"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        AMBIGUOUS = "AMBIGUOUS", "Ambiguous"
        CANCELED_PRE_CALL = "CANCELED_PRE_CALL", "Canceled before call"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AIRun, on_delete=models.PROTECT, related_name="provider_calls")
    generation = models.PositiveSmallIntegerField()
    phase = models.CharField(max_length=12, choices=Phase.choices, default=Phase.NORMAL)
    status = models.CharField(max_length=24, choices=Status.choices)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    reserved_usd = models.DecimalField(max_digits=12, decimal_places=6)
    actual_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    request_id = models.CharField(max_length=128, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_hit_tokens = models.PositiveIntegerField(default=0)
    finish_reason = models.CharField(max_length=64, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run_id", "generation"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "generation"], name="ai_unique_provider_call_generation"
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_usd__gte=0, actual_usd__gte=0),
                name="ai_provider_call_cost_nonnegative",
            ),
        ]


class AIRetryDispatchOutbox(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DISPATCHING = "DISPATCHING", "Dispatching"
        ACKED = "ACKED", "Acknowledged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AIRun, on_delete=models.PROTECT, related_name="retry_outbox")
    retry_generation = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    available_at = models.DateTimeField()
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["run", "retry_generation"], name="ai_unique_retry_outbox_generation"
        )]
