from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.identity.models import Organization

from .models import ApprovalRecord, AuditLog, approval_audit_writes


@transaction.atomic
def record_system_audit_event(
    *,
    organization: Organization,
    job_id,
    claim_token,
    object_type: str,
    object_id,
    action: str,
    status: str,
    object_version: int,
    comment: str = "",
    before_metadata: dict[str, object] | None = None,
    after_metadata: dict[str, object] | None = None,
) -> AuditLog:
    """Append a system event only for the currently owned retention attempt."""
    from apps.jobs.models import Job
    from apps.jobs.services import JobService

    try:
        job = JobService._locked(job_id, organization=organization)
    except Job.DoesNotExist as error:
        raise PermissionDenied(
            "System audit job must belong to the event organization."
        ) from error
    if job.type != Job.Type.RETENTION_CLEANUP:
        raise PermissionDenied("System audit requires a retention cleanup job.")
    try:
        JobService._require_owner(job, claim_token)
    except ValueError as error:
        raise PermissionDenied(
            "System audit requires the current retention job attempt."
        ) from error
    with approval_audit_writes():
        return AuditLog.objects.create(
            organization=organization,
            object_type=object_type,
            object_id=object_id,
            action=action,
            status=status,
            object_version=object_version,
            actor=None,
            comment=comment,
            before_metadata=before_metadata or {},
            after_metadata=after_metadata or {},
        )


@transaction.atomic
def record_audit_event(
    *,
    organization: Organization,
    object_type: str,
    object_id,
    action: str,
    status: str,
    object_version: int,
    actor: AbstractBaseUser | None,
    required_permission: str,
    comment: str = "",
    before_metadata: dict[str, object] | None = None,
    after_metadata: dict[str, object] | None = None,
) -> AuditLog:
    """Append an audit-only event for an authorized human actor."""
    from apps.identity.models import Membership
    from apps.identity.services import get_active_membership, require_permission

    if actor is None:
        raise PermissionDenied("Audit events require an authorized human actor.")
    try:
        membership = get_active_membership(user=actor)
    except Membership.DoesNotExist as error:
        raise PermissionDenied(
            "Audit events require an active organization membership."
        ) from error
    if membership.organization_id != organization.id:
        raise PermissionDenied(
            "Audit actor must belong to the event organization."
        )
    require_permission(
        membership=membership,
        permission=required_permission,
    )
    with approval_audit_writes():
        return AuditLog.objects.create(
            organization=organization,
            object_type=object_type,
            object_id=object_id,
            action=action,
            status=status,
            object_version=object_version,
            actor=actor,
            comment=comment,
            before_metadata=before_metadata or {},
            after_metadata=after_metadata or {},
        )


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
    if action == "REJECT" and not comment.strip():
        raise ValueError("Reject comment must not be empty.")
    before = before_metadata or {}
    after = after_metadata or {}
    with approval_audit_writes():
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
