import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import OrganizationScopedModel


_publishing_write = ContextVar("publishing_service_write", default=False)


@contextmanager
def publishing_writes():
    token = _publishing_write.set(True)
    try:
        yield
    finally:
        _publishing_write.reset(token)


class ProtectedPublishingQuerySet(models.QuerySet):
    @staticmethod
    def _guard():
        if not _publishing_write.get():
            raise ValidationError("Publishing history may change only through services.")

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
        raise ValidationError("Publishing history cannot be deleted.")


class ProtectedPublishingModel(OrganizationScopedModel):
    objects = models.Manager.from_queryset(ProtectedPublishingQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not _publishing_write.get():
            raise ValidationError("Publishing history may change only through services.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Publishing history cannot be deleted.")


class PublishTask(ProtectedPublishingModel):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"

    platform_content = models.ForeignKey(
        "content.PlatformContent", on_delete=models.PROTECT, related_name="publish_tasks"
    )
    content_version = models.PositiveIntegerField()
    social_account = models.ForeignKey(
        "platforms.SocialAccount", on_delete=models.PROTECT, related_name="publish_tasks"
    )
    platform = models.ForeignKey(
        "platforms.Platform", on_delete=models.PROTECT, related_name="publish_tasks"
    )
    connector_code = models.CharField(max_length=64, default="mock")
    idempotency_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    requested_timezone = models.CharField(max_length=64, default="UTC")
    claim_token = models.UUIDField(null=True, blank=True)
    attempt_number = models.PositiveIntegerField(default=0)
    retry_not_before = models.DateTimeField(null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name="created_publish_tasks",
    )

    class Meta(ProtectedPublishingModel.Meta):
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="publishing_unique_idempotency_key",
            ),
        ]


class PublishAttempt(ProtectedPublishingModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"
        STALE = "STALE", "Stale"

    task = models.ForeignKey(PublishTask, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveIntegerField()
    claim_token = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    request_fingerprint = models.CharField(max_length=64)
    outcome = models.CharField(max_length=32, blank=True)
    error = models.JSONField(null=True, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(ProtectedPublishingModel.Meta):
        ordering = ["task_id", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "number"], name="publishing_unique_attempt_number"
            ),
        ]


class PublishedPost(ProtectedPublishingModel):
    task = models.OneToOneField(
        PublishTask, on_delete=models.PROTECT, related_name="published_post"
    )
    attempt = models.OneToOneField(
        PublishAttempt, on_delete=models.PROTECT, related_name="published_post"
    )
    platform_content = models.ForeignKey(
        "content.PlatformContent", on_delete=models.PROTECT, related_name="published_posts"
    )
    social_account = models.ForeignKey(
        "platforms.SocialAccount", on_delete=models.PROTECT, related_name="published_posts"
    )
    external_id = models.CharField(max_length=255)
    published_at = models.DateTimeField()

    class Meta(ProtectedPublishingModel.Meta):
        ordering = ["-published_at", "-id"]
