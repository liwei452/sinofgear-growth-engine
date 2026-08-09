import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
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
