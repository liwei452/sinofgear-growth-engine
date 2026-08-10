from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.db.models.expressions import BaseExpression
from django.utils import timezone

from apps.assets.models import MaterialAsset
from apps.common.models import OrganizationScopedModel
from apps.common.security import scrub_secrets
from apps.jobs.models import Job


_evidence_service_write: ContextVar[bool] = ContextVar(
    "source_evidence_service_write", default=False
)
_ingestion_row_service_write: ContextVar[bool] = ContextVar(
    "source_ingestion_row_service_write", default=False
)
_ingestion_batch_state_service_write: ContextVar[bool] = ContextVar(
    "source_ingestion_batch_state_service_write", default=False
)
_ingestion_batch_retention_service_write: ContextVar[bool] = ContextVar(
    "source_ingestion_batch_retention_service_write", default=False
)
_evidence_trusted_asset_fields: ContextVar[dict[str, object] | None] = ContextVar(
    "source_evidence_trusted_asset_fields", default=None
)
_EVIDENCE_TRUSTED_ASSET_CAPABILITY = object()


@contextmanager
def evidence_service_writes():
    token = _evidence_service_write.set(True)
    try:
        yield
    finally:
        _evidence_service_write.reset(token)


@contextmanager
def ingestion_row_service_writes():
    token = _ingestion_row_service_write.set(True)
    try:
        yield
    finally:
        _ingestion_row_service_write.reset(token)


@contextmanager
def _ingestion_batch_state_writes():
    token = _ingestion_batch_state_service_write.set(True)
    try:
        yield
    finally:
        _ingestion_batch_state_service_write.reset(token)


@contextmanager
def _ingestion_batch_retention_writes():
    token = _ingestion_batch_retention_service_write.set(True)
    try:
        yield
    finally:
        _ingestion_batch_retention_service_write.reset(token)


@contextmanager
def _evidence_trusted_asset_writes(*, _capability=None, **asset_fields):
    if _capability is not _EVIDENCE_TRUSTED_ASSET_CAPABILITY:
        raise ValidationError("Trusted evidence asset validation is service-internal.")
    token = _evidence_trusted_asset_fields.set(asset_fields)
    try:
        yield
    finally:
        _evidence_trusted_asset_fields.reset(token)


class ServiceWriteQuerySet(models.QuerySet):
    def _require_service_write(self) -> None:
        self.model._require_service_write()

    @transaction.atomic
    def update(self, **kwargs):
        self._require_service_write()
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for immutable source field '{field}'."
                    )
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        self._require_service_write()
        if kwargs.get("update_conflicts"):
            raise ValidationError("Immutable source bulk upserts are not supported.")
        rows = list(objs)
        for row in rows:
            row.full_clean(validate_unique=False, validate_constraints=False)
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        self._require_service_write()
        field_names = [field.name if hasattr(field, "name") else str(field) for field in fields]
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*field_names, "updated_at"])
        return len(rows)

    def delete(self):
        self._require_service_write()
        return super().delete()


class ServiceWriteManager(models.Manager.from_queryset(ServiceWriteQuerySet)):
    pass


class ServiceWriteModel(OrganizationScopedModel):
    objects = ServiceWriteManager()
    service_write_context: ContextVar[bool]
    service_write_error = "Immutable source history may change only through its service."

    class Meta:
        abstract = True

    @classmethod
    def _require_service_write(cls) -> None:
        if not cls.service_write_context.get():
            raise ValidationError(cls.service_write_error)

    def save(self, *args, **kwargs):
        type(self)._require_service_write()
        _require_organization_immutable(self)
        self.full_clean(
            exclude=self._service_validation_exclusions(),
            validate_unique=False,
            validate_constraints=False,
        )
        return super().save(*args, **kwargs)

    def _service_validation_exclusions(self):
        return set()

    def delete(self, *args, **kwargs):
        type(self)._require_service_write()
        return super().delete(*args, **kwargs)


SHA256_VALIDATOR = RegexValidator(
    r"^[0-9a-f]{64}$", "Content hash must be lowercase SHA-256."
)

SOURCE_SECRET_KEY_FRAGMENTS = frozenset(
    {
        "captcha",
        "verificationcode",
        "verifycode",
        "onetimecode",
        "onetimepassword",
        "challengeanswer",
    }
)
SOURCE_RAW_HEADER_KEYS = frozenset(
    {"header", "headers", "httpheader", "httpheaders", "rawheader", "rawheaders"}
)


def _validate_related_organization(instance, field_name: str, errors: dict[str, str]) -> None:
    related_id = getattr(instance, f"{field_name}_id", None)
    if not instance.organization_id or not related_id:
        return
    related = getattr(instance, field_name)
    if related.organization_id != instance.organization_id:
        errors[field_name] = f"{field_name.replace('_', ' ').title()} must belong to the same organization."


def _sanitize_source_json_tree(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized_key = "".join(character for character in str(key).casefold() if character.isalnum())
            if normalized_key in SOURCE_RAW_HEADER_KEYS or any(
                fragment in normalized_key for fragment in SOURCE_SECRET_KEY_FRAGMENTS
            ):
                continue
            cleaned[key] = _sanitize_source_json_tree(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_source_json_tree(item) for item in value]
    return value


def sanitize_source_json(value):
    """Return a detached JSON tree with source credentials/challenges removed."""
    return _sanitize_source_json_tree(scrub_secrets(value))


def _require_organization_immutable(instance) -> None:
    if instance._state.adding or not instance.pk:
        return
    persisted_organization_id = (
        type(instance)._base_manager.only("organization_id").get(pk=instance.pk).organization_id
    )
    if instance.organization_id != persisted_organization_id:
        raise ValidationError({"organization": "Organization is immutable after creation."})


class ValidatedSourceQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for source field '{field}'."
                    )
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Source bulk upserts are not supported.")
        rows = list(objs)
        for row in rows:
            row.full_clean(validate_unique=False, validate_constraints=False)
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        field_names = [field.name if hasattr(field, "name") else str(field) for field in fields]
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*field_names, "updated_at"])
        return len(rows)

    def delete(self):
        if getattr(self.model, "deletion_protected", False):
            protected = list(self)
            if protected:
                raise ProtectedError("Source ingestion history cannot be deleted.", protected)
            return 0, {}
        return super().delete()


class ValidatedSourceManager(models.Manager.from_queryset(ValidatedSourceQuerySet)):
    pass


class IngestionBatchQuerySet(ValidatedSourceQuerySet):
    _MUTABLE_STATE_FIELDS = frozenset(
        {
            "status",
            "received_count",
            "accepted_count",
            "duplicate_count",
            "failed_count",
            "row_errors",
            "started_at",
            "finished_at",
            "updated_at",
        }
    )

    def _service_update_state(self, **values):
        if not _ingestion_batch_state_service_write.get():
            raise ValidationError(
                "Ingestion batch state may change only through its service."
            )
        unexpected = set(values) - self._MUTABLE_STATE_FIELDS
        if unexpected:
            raise ValidationError(
                "Ingestion batch mutable state writer cannot change input identity."
            )
        safe_values = dict(values)
        if "row_errors" in safe_values:
            safe_values["row_errors"] = sanitize_source_json(safe_values["row_errors"])
        safe_values["updated_at"] = safe_values.get("updated_at") or timezone.now()
        model_instance = self.model()
        for field_name, value in safe_values.items():
            self.model._meta.get_field(field_name).clean(value, model_instance)
        if models.QuerySet.update(self, **safe_values) != 1:
            raise self.model.DoesNotExist
        return safe_values

    def _service_redact_input_reference(self, *, input_reference):
        """Narrow writer for irreversible retention tombstones on a locked batch."""
        if not _ingestion_batch_retention_service_write.get():
            raise ValidationError(
                "Ingestion batch retention data may change only through its service."
            )
        safe_reference = sanitize_source_json(input_reference)
        model_instance = self.model()
        self.model._meta.get_field("input_reference").clean(
            safe_reference, model_instance
        )
        safe_values = {
            "input_reference": safe_reference,
            "updated_at": timezone.now(),
        }
        if models.QuerySet.update(self, **safe_values) != 1:
            raise self.model.DoesNotExist
        return safe_values


class IngestionBatchManager(models.Manager.from_queryset(IngestionBatchQuerySet)):
    pass


class ValidatedOrganizationModel(OrganizationScopedModel):
    objects = ValidatedSourceManager()
    deletion_protected = False

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        _require_organization_immutable(self)
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.deletion_protected:
            raise ProtectedError("Source ingestion history cannot be deleted.", [self])
        return super().delete(*args, **kwargs)


class MonitoringTarget(ValidatedOrganizationModel):
    class TargetType(models.TextChoices):
        ACCOUNT = "ACCOUNT", "Account"
        POST = "POST", "Post"
        KEYWORD = "KEYWORD", "Keyword"
        INDUSTRY_PAGE = "INDUSTRY_PAGE", "Industry page"

    class CollectionMode(models.TextChoices):
        MANUAL_URL = "MANUAL_URL", "Manual URL"
        SCREENSHOT = "SCREENSHOT", "Screenshot"
        FILE_IMPORT = "FILE_IMPORT", "File import"
        PASTE = "PASTE", "Paste"
        OFFICIAL_API = "OFFICIAL_API", "Official API"

    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    collection_mode = models.CharField(max_length=16, choices=CollectionMode.choices)
    platform = models.CharField(max_length=32)
    external_reference = models.CharField(max_length=255, blank=True)
    normalized_url = models.URLField(max_length=2048, blank=True)
    label = models.CharField(max_length=255)
    schedule = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    capability_snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_monitoring_targets",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(external_reference__gt="") | models.Q(normalized_url__gt=""),
                name="sources_target_has_locator",
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.schedule = sanitize_source_json(self.schedule)
        self.capability_snapshot = sanitize_source_json(self.capability_snapshot)
        if self.normalized_url:
            from .services import normalize_source_url

            self.normalized_url = normalize_source_url(self.normalized_url)
        if not self.external_reference and not self.normalized_url:
            raise ValidationError(
                "Monitoring target requires an external reference or normalized URL."
            )


class IngestionBatch(ValidatedOrganizationModel):
    deletion_protected = True
    objects = IngestionBatchManager()

    class SourceType(models.TextChoices):
        API = "API", "API"
        URL = "URL", "URL"
        SCREENSHOT = "SCREENSHOT", "Screenshot"
        CSV = "CSV", "CSV"
        JSON = "JSON", "JSON"
        PASTE = "PASTE", "Paste"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        PARTIAL_SUCCESS = "PARTIAL_SUCCESS", "Partial success"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    monitoring_target = models.ForeignKey(
        MonitoringTarget,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_batches",
    )
    job = models.OneToOneField(
        Job,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_batch",
    )
    input_reference = models.JSONField(default=dict, blank=True)
    received_count = models.PositiveIntegerField(default=0)
    accepted_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    row_errors = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(max_length=128)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_ingestion_batches",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="sources_unique_batch_key",
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.input_reference = sanitize_source_json(self.input_reference)
        self.row_errors = sanitize_source_json(self.row_errors)
        errors: dict[str, str] = {}
        self._validate_bound_input_identity(errors)
        if isinstance(self.input_reference, (str, bytes)):
            errors["input_reference"] = (
                "Ingestion batches require a prepared structured input reference."
            )
        elif self.source_type != self.SourceType.API:
            from .importers import validate_prepared_import_reference

            try:
                validate_prepared_import_reference(
                    self.input_reference, source_type=self.source_type
                )
            except ValidationError as error:
                errors["input_reference"] = " ".join(error.messages)
        _validate_related_organization(self, "monitoring_target", errors)
        _validate_related_organization(self, "job", errors)
        if errors:
            raise ValidationError(errors)

    def _validate_bound_input_identity(self, errors: dict[str, str]) -> None:
        if self._state.adding or not self.pk:
            return
        persisted = (
            type(self)._base_manager.filter(pk=self.pk)
            .values(
                "source_type",
                "input_reference",
                "idempotency_key",
                "monitoring_target_id",
                "job_id",
            )
            .first()
        )
        if persisted is None:
            return
        identity_fields = (
            "source_type",
            "input_reference",
            "idempotency_key",
            "monitoring_target_id",
        )
        identity_changed = any(
            getattr(self, field_name) != persisted[field_name]
            for field_name in identity_fields
        )
        binding_changed = (
            persisted["job_id"] is not None and self.job_id != persisted["job_id"]
        )
        binding_with_changed_input = (
            persisted["job_id"] is None
            and self.job_id is not None
            and identity_changed
        )
        if (
            persisted["job_id"] is not None and identity_changed
        ) or binding_changed or binding_with_changed_input:
            errors["job"] = "Bound ingestion batch input identity is immutable."


class SourceContent(ValidatedOrganizationModel):
    monitoring_target = models.ForeignKey(
        MonitoringTarget,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_contents",
    )
    platform = models.CharField(max_length=32)
    external_id = models.CharField(max_length=255, blank=True, default="")
    canonical_url = models.URLField(max_length=2048)
    author_public_name = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=500, blank=True)
    original_text = models.TextField(blank=True)
    public_published_at = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=16, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    content_hash = models.CharField(max_length=64, validators=[SHA256_VALIDATOR])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_source_contents",
    )

    class Meta:
        ordering = ["-captured_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "platform", "external_id"],
                condition=~models.Q(external_id=""),
                name="sources_unique_content_external",
            ),
            models.UniqueConstraint(
                fields=["organization", "content_hash", "canonical_url"],
                condition=models.Q(external_id=""),
                name="sources_unique_content_fallback",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        from .services import normalize_source_url

        self.external_id = self.external_id or ""
        self.canonical_url = normalize_source_url(self.canonical_url)
        errors: dict[str, str] = {}
        _validate_related_organization(self, "monitoring_target", errors)
        if errors:
            raise ValidationError(errors)


class SourceSignal(ValidatedOrganizationModel):
    class SignalType(models.TextChoices):
        COMMENT = "COMMENT", "Comment"
        POST_AUTHOR = "POST_AUTHOR", "Post author"
        CHANNEL_OWNER = "CHANNEL_OWNER", "Channel owner"
        PROFILE_MATCH = "PROFILE_MATCH", "Profile match"
        MENTION = "MENTION", "Mention"
        HASHTAG_MATCH = "HASHTAG_MATCH", "Hashtag match"

    monitoring_target = models.ForeignKey(
        MonitoringTarget,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_signals",
    )
    source_content = models.ForeignKey(
        SourceContent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_signals",
    )
    signal_type = models.CharField(max_length=16, choices=SignalType.choices)
    platform = models.CharField(max_length=32)
    external_id = models.CharField(max_length=255, blank=True, default="")
    captured_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_source_signals",
    )

    class Meta:
        ordering = ["-captured_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monitoring_target__isnull=False)
                | models.Q(source_content__isnull=False),
                name="sources_signal_has_source",
            ),
            models.UniqueConstraint(
                fields=["organization", "platform", "external_id"],
                condition=~models.Q(external_id=""),
                name="sources_unique_signal_external",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        self.external_id = self.external_id or ""
        errors: dict[str, str] = {}
        _validate_related_organization(self, "monitoring_target", errors)
        _validate_related_organization(self, "source_content", errors)
        if not self.monitoring_target_id and not self.source_content_id:
            errors["source_content"] = "A monitoring target or source content is required."
        if self.monitoring_target_id and self.source_content_id:
            content_target_id = self.source_content.monitoring_target_id
            if content_target_id and content_target_id != self.monitoring_target_id:
                errors["source_content"] = "Source content conflicts with the monitoring target."
        if errors:
            raise ValidationError(errors)


class SourceEvidence(ServiceWriteModel):
    class EvidenceType(models.TextChoices):
        PUBLIC_TEXT = "PUBLIC_TEXT", "Public text"
        PUBLIC_METADATA = "PUBLIC_METADATA", "Public metadata"
        SCREENSHOT = "SCREENSHOT", "Screenshot"
        IMPORT_ROW = "IMPORT_ROW", "Import row"

    class CollectionMethod(models.TextChoices):
        API = "API", "API"
        URL = "URL", "URL"
        SCREENSHOT = "SCREENSHOT", "Screenshot"
        CSV = "CSV", "CSV"
        JSON = "JSON", "JSON"
        PASTE = "PASTE", "Paste"

    class Availability(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE", "Source unavailable"
        REDACTED_BY_RETENTION = "REDACTED_BY_RETENTION", "Redacted by retention"

    class RetentionClass(models.TextChoices):
        TRANSIENT_30D = "TRANSIENT_30D", "Transient 30 days"
        CONFIRMED = "CONFIRMED", "Confirmed"
        HANDOFF_PROTECTED = "HANDOFF_PROTECTED", "Handoff protected"

    service_write_context = _evidence_service_write
    service_write_error = "Source evidence may change only through its service."

    source_signal = models.ForeignKey(
        SourceSignal, on_delete=models.PROTECT, related_name="evidence"
    )
    evidence_type = models.CharField(max_length=16, choices=EvidenceType.choices)
    original_text = models.TextField(blank=True)
    translated_text = models.TextField(blank=True)
    translated_language = models.CharField(max_length=16, blank=True)
    source_url = models.URLField(max_length=2048, blank=True)
    platform = models.CharField(max_length=32)
    public_published_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    collection_method = models.CharField(max_length=16, choices=CollectionMethod.choices)
    language = models.CharField(max_length=16, blank=True)
    screenshot_asset = models.ForeignKey(
        MaterialAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="screenshot_source_evidence",
    )
    import_asset = models.ForeignKey(
        MaterialAsset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_source_evidence",
    )
    content_hash = models.CharField(max_length=64, validators=[SHA256_VALIDATOR])
    availability = models.CharField(
        max_length=24, choices=Availability.choices, default=Availability.AVAILABLE
    )
    retention_class = models.CharField(
        max_length=24, choices=RetentionClass.choices, default=RetentionClass.TRANSIENT_30D
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_source_evidence",
    )

    class Meta:
        ordering = ["-captured_at", "-id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "content_hash"],
                name="sources_unique_evidence_hash",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if self.source_url:
            from .services import normalize_source_url

            self.source_url = normalize_source_url(self.source_url)
        errors: dict[str, str] = {}
        _validate_related_organization(self, "source_signal", errors)
        _validate_related_organization(self, "screenshot_asset", errors)
        _validate_related_organization(self, "import_asset", errors)
        if errors:
            raise ValidationError(errors)

    def _service_validation_exclusions(self):
        trusted_fields = _evidence_trusted_asset_fields.get()
        if trusted_fields is None:
            return set()
        for field_name, expected_asset in trusted_fields.items():
            if field_name not in {"screenshot_asset", "import_asset"}:
                raise ValidationError("Unsupported trusted evidence asset field.")
            if getattr(self, field_name) is not expected_asset:
                raise ValidationError(
                    {field_name: "Trusted evidence asset identity changed before persistence."}
                )
        return set(trusted_fields)


class IngestionRow(ServiceWriteModel):
    class Outcome(models.TextChoices):
        ACCEPTED = "ACCEPTED", "Accepted"
        DUPLICATE = "DUPLICATE", "Duplicate"
        FAILED = "FAILED", "Failed"

    service_write_context = _ingestion_row_service_write
    service_write_error = "Ingestion rows may change only through their service."

    batch = models.ForeignKey(IngestionBatch, on_delete=models.PROTECT, related_name="rows")
    row_number = models.PositiveIntegerField()
    normalized_input = models.JSONField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    error = models.JSONField(null=True, blank=True)
    source_content = models.ForeignKey(
        SourceContent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_rows",
    )
    source_signal = models.ForeignKey(
        SourceSignal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_rows",
    )
    source_evidence = models.ForeignKey(
        SourceEvidence,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingestion_rows",
    )

    class Meta:
        ordering = ["batch_id", "row_number"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"], name="sources_unique_batch_row"
            )
        ]

    def clean(self) -> None:
        super().clean()
        self.normalized_input = sanitize_source_json(self.normalized_input)
        self.error = sanitize_source_json(self.error)
        errors: dict[str, str] = {}
        for field_name in (
            "batch",
            "source_content",
            "source_signal",
            "source_evidence",
        ):
            _validate_related_organization(self, field_name, errors)
        if errors:
            raise ValidationError(errors)
