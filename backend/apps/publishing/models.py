import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import OrganizationScopedModel


_publishing_write = ContextVar("publishing_service_write", default=False)

LIVE_PUBLISH_TASK_STATUSES = (
    "SCHEDULED",
    "QUEUED",
    "RUNNING",
    "SUBMITTED",
    "SUBMISSION_UNKNOWN",
    "NEEDS_ATTENTION",
    "SUCCEEDED",
)


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
        if self.model.__name__ == "PublishReconciliationAttempt":
            raise ValidationError("Publishing reconciliation audits are append-only.")
        self._guard()
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if self.model.__name__ == "PublishReconciliationAttempt":
            raise ValidationError("Publishing reconciliation audits must be appended individually.")
        self._guard()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if self.model.__name__ == "PublishReconciliationAttempt":
            raise ValidationError("Publishing reconciliation audits are append-only.")
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
        SUBMITTED = "SUBMITTED", "Submitted"
        SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN", "Submission unknown"
        NEEDS_ATTENTION = "NEEDS_ATTENTION", "Needs attention"
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
    status = models.CharField(max_length=32, choices=Status.choices)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    requested_timezone = models.CharField(max_length=64, default="UTC")
    claim_token = models.UUIDField(null=True, blank=True)
    attempt_number = models.PositiveIntegerField(default=0)
    retry_not_before = models.DateTimeField(null=True, blank=True)
    last_error = models.JSONField(null=True, blank=True)
    provider_submission_id = models.CharField(max_length=255, blank=True, default="")
    provider_request_fingerprint = models.CharField(max_length=64, blank=True, default="")
    provider_call_started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    reconciliation_attempt_number = models.PositiveIntegerField(default=0)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    next_reconcile_at = models.DateTimeField(null=True, blank=True)
    reconciliation_error_code = models.CharField(max_length=64, blank=True, default="")
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
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "platform_content",
                    "content_version",
                    "social_account",
                ],
                condition=models.Q(status__in=LIVE_PUBLISH_TASK_STATUSES),
                name="publishing_unique_live_content_account",
            ),
        ]


class PublishAttempt(ProtectedPublishingModel):
    class Status(models.TextChoices):
        RUNNING = "RUNNING", "Running"
        SUBMITTED = "SUBMITTED", "Submitted"
        SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN", "Submission unknown"
        NEEDS_ATTENTION = "NEEDS_ATTENTION", "Needs attention"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELED = "CANCELED", "Canceled"
        STALE = "STALE", "Stale"

    task = models.ForeignKey(PublishTask, on_delete=models.PROTECT, related_name="attempts")
    number = models.PositiveIntegerField()
    claim_token = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=32, choices=Status.choices)
    request_fingerprint = models.CharField(max_length=64)
    outcome = models.CharField(max_length=32, blank=True)
    error = models.JSONField(null=True, blank=True)
    retry_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    provider_submission_id = models.CharField(max_length=255, blank=True, default="")
    provider_request_fingerprint = models.CharField(max_length=64, blank=True, default="")
    provider_call_started_at = models.DateTimeField(null=True, blank=True)
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


class PublishReconciliationAttempt(ProtectedPublishingModel):
    class Mode(models.TextChoices):
        EXACT_ID = "EXACT_ID", "Exact provider id"
        UNKNOWN_MATCH = "UNKNOWN_MATCH", "Unknown submission match"
        MANUAL = "MANUAL", "Manual resolution"

    class Provider(models.TextChoices):
        BUFFER = "BUFFER", "Buffer"

    class Result(models.TextChoices):
        DEFERRED = "DEFERRED", "Deferred"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        NEEDS_ATTENTION = "NEEDS_ATTENTION", "Needs attention"
        STALE = "STALE", "Stale snapshot"
        MATCHED = "MATCHED", "Unique match"

    publish_task = models.ForeignKey(
        PublishTask, on_delete=models.PROTECT, related_name="reconciliation_attempts"
    )
    sequence_number = models.PositiveIntegerField()
    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.EXACT_ID)
    provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.BUFFER)
    provider_submission_id = models.CharField(max_length=255)
    observed_provider_status = models.CharField(max_length=32, blank=True, default="")
    result = models.CharField(max_length=32, choices=Result.choices)
    safe_error_code = models.CharField(max_length=64, blank=True, default="")
    provider_post_id = models.CharField(max_length=255, blank=True, default="")
    provider_channel_id = models.CharField(max_length=255, blank=True, default="")
    provider_sent_at = models.DateTimeField(null=True, blank=True)
    candidate_count = models.PositiveIntegerField(default=0)
    candidate_search_truncated = models.BooleanField(null=True, default=None)
    matched_provider_post_id = models.CharField(max_length=255, blank=True, default="")
    candidate_set_fingerprint = models.CharField(max_length=64, blank=True, default="")
    query_window_start = models.DateTimeField(null=True, blank=True)
    query_window_end = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="publish_reconciliation_resolutions",
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Publishing reconciliation audits are append-only.")
        if (
            self.publish_task_id
            and self.organization_id != self.publish_task.organization_id
        ):
            raise ValidationError("Reconciliation audit organization must match its task.")
        return super().save(*args, **kwargs)

    class Meta(ProtectedPublishingModel.Meta):
        ordering = ["publish_task_id", "sequence_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["publish_task", "sequence_number"],
                name="publishing_unique_reconciliation_number",
            ),
        ]


class PostMetric(ProtectedPublishingModel):
    post = models.ForeignKey(
        PublishedPost, on_delete=models.PROTECT, related_name="metrics",
    )
    collected_on = models.DateField()
    impressions = models.PositiveIntegerField(default=0)
    plays = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=32, default="demo")

    class Meta(ProtectedPublishingModel.Meta):
        ordering = ["-collected_on", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "collected_on"],
                name="publishing_unique_post_metric_day",
            ),
        ]
