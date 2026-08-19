import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


_audit_write = ContextVar("approval_audit_write", default=False)


@contextmanager
def approval_audit_writes():
    token = _audit_write.set(True)
    try:
        yield
    finally:
        _audit_write.reset(token)


class ImmutableAuditQuerySet(models.QuerySet):
    def _guard(self):
        if not _audit_write.get():
            raise ValidationError("Approval audit history is immutable.")

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
        raise ValidationError("Approval audit history cannot be deleted.")


class ImmutableAuditModel(models.Model):
    objects = models.Manager.from_queryset(ImmutableAuditQuerySet)()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if not _audit_write.get():
            raise ValidationError("Approval audit history is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Approval audit history cannot be deleted.")


class ReviewAction(models.TextChoices):
    SUBMIT = "SUBMIT", "Submit for review"
    APPROVE = "APPROVE", "Approve"
    AUTO_APPROVE = "AUTO_APPROVE", "Auto approve"
    REJECT = "REJECT", "Reject"
    DEPRECATE = "DEPRECATE", "Deprecate"
    ARCHIVE = "ARCHIVE", "Archive"


class ApprovalRecord(ImmutableAuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT, related_name="approval_records")
    object_type = models.CharField(max_length=128)
    object_id = models.UUIDField()
    action = models.CharField(max_length=16, choices=ReviewAction.choices)
    status = models.CharField(max_length=32)
    object_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_records")
    comment = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["object_type", "object_id"], name="audit_approval_object_idx")]


class AuditLog(ImmutableAuditModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT, related_name="audit_logs")
    object_type = models.CharField(max_length=128)
    object_id = models.UUIDField()
    action = models.CharField(max_length=16, choices=ReviewAction.choices)
    status = models.CharField(max_length=32)
    object_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="audit_logs")
    comment = models.TextField(blank=True)
    before_metadata = models.JSONField(default=dict)
    after_metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["object_type", "object_id"], name="audit_log_object_idx")]
