import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


_service_write: ContextVar[bool] = ContextVar("job_service_write", default=False)


@contextmanager
def job_service_writes():
    token = _service_write.set(True)
    try:
        yield
    finally:
        _service_write.reset(token)


class ProtectedJobQuerySet(models.QuerySet):
    @staticmethod
    def _require_service_write() -> None:
        if not _service_write.get():
            raise ValidationError("Job history may change only through JobService.")

    def update(self, **kwargs):
        self._require_service_write()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        self._require_service_write()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        self._require_service_write()
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        raise ValidationError("Job history cannot be deleted.")


class ProtectedJobManager(models.Manager.from_queryset(ProtectedJobQuerySet)):
    pass


class ProtectedJobModel(models.Model):
    objects = ProtectedJobManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _service_write.get():
            raise ValidationError("Job history may change only through JobService.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Job history cannot be deleted.")


class Job(ProtectedJobModel):
    class Type(models.TextChoices):
        CONTENT_GENERATE = "CONTENT_GENERATE", "Content generate"
        CONTENT_RECOMMEND = "CONTENT_RECOMMEND", "Content recommend"
        ASSET_UNDERSTAND = "ASSET_UNDERSTAND", "Asset understand"
        CONTENT_PLATFORM_VARIANTS = "CONTENT_PLATFORM_VARIANTS", "Content platform variants"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        RETRY_QUEUED = "RETRY_QUEUED", "Retry queued"
        CANCELED = "CANCELED", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT, related_name="jobs"
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    input_snapshot = models.JSONField()
    result_reference = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128)
    attempt = models.PositiveSmallIntegerField(default=1)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_by = models.CharField(max_length=255, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "type", "idempotency_key"],
                name="jobs_unique_idempotent_request",
            ),
            models.CheckConstraint(
                condition=models.Q(progress__gte=0, progress__lte=100),
                name="jobs_progress_bounded",
            ),
        ]


class JobAttempt(ProtectedJobModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveSmallIntegerField()
    claim_token = models.UUIDField(unique=True)
    worker_id = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    result_reference = models.JSONField(null=True, blank=True)

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        ordering = ["job_id", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "number"], name="jobs_unique_attempt_number"
            )
        ]
