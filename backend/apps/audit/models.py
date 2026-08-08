import uuid

from django.conf import settings
from django.db import models


class ReviewAction(models.TextChoices):
    SUBMIT = "SUBMIT", "Submit for review"
    APPROVE = "APPROVE", "Approve"
    REJECT = "REJECT", "Reject"
    DEPRECATE = "DEPRECATE", "Deprecate"


class ApprovalRecord(models.Model):
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


class AuditLog(models.Model):
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
