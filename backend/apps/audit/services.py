from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction

from apps.identity.models import Organization

from .models import ApprovalRecord, AuditLog


@transaction.atomic
def record_review_transition(
    *,
    organization: Organization,
    object_type: str,
    object_id,
    action: str,
    status: str,
    object_version: int,
    actor: AbstractBaseUser,
    comment: str = "",
    before_metadata: dict[str, object] | None = None,
    after_metadata: dict[str, object] | None = None,
) -> tuple[ApprovalRecord, AuditLog]:
    before = before_metadata or {}
    after = after_metadata or {}
    approval = ApprovalRecord.objects.create(
        organization=organization,
        object_type=object_type,
        object_id=object_id,
        action=action,
        status=status,
        object_version=object_version,
        actor=actor,
        comment=comment,
        metadata={"before": before, "after": after},
    )
    audit = AuditLog.objects.create(
        organization=organization,
        object_type=object_type,
        object_id=object_id,
        action=action,
        status=status,
        object_version=object_version,
        actor=actor,
        comment=comment,
        before_metadata=before,
        after_metadata=after,
    )
    return approval, audit
