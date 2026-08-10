import uuid

import pytest
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.audit.models import ApprovalRecord, AuditLog
from apps.audit.services import (
    record_audit_event,
    record_review_transition,
    record_system_audit_event,
)
from apps.identity.permissions import PermissionCode
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.knowledge.models import KnowledgeConcept
from apps.knowledge.services import OntologyContextService

from apps.knowledge.tests.conftest import create_member_client, make_concept


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("operation", "expected_action", "expected_status"),
    [("approve", "APPROVE", "APPROVED"), ("reject", "REJECT", "REJECTED"), ("deprecate", "DEPRECATE", "DEPRECATED")],
)
def test_review_transition_writes_matching_approval_and_audit_records(
    organizations, roles, operation, expected_action, expected_status
) -> None:
    own, _ = organizations
    membership, _ = create_member_client(organization=own, role=roles["ADMINISTRATOR"], username=f"admin-{operation}")
    initial_status = KnowledgeConcept.Status.APPROVED if operation == "deprecate" else KnowledgeConcept.Status.SUGGESTED
    concept = make_concept(code=f"AUDIT_{operation}", organization=own, status=initial_status)
    kwargs = {"comment": "Not sufficiently supported"} if operation == "reject" else {}

    result = getattr(OntologyContextService(own), operation)(concept.id, actor=membership.user, **kwargs)

    approval = ApprovalRecord.objects.get(object_id=concept.id, action=expected_action)
    audit = AuditLog.objects.get(object_id=concept.id, action=expected_action)
    assert result.status == expected_status
    assert approval.organization == own == audit.organization
    assert approval.object_type == audit.object_type == "knowledge.KnowledgeConcept"
    assert approval.object_version == audit.object_version == result.version
    assert approval.actor == audit.actor == membership.user
    assert audit.before_metadata["status"] == initial_status
    assert audit.after_metadata["status"] == expected_status


@pytest.mark.django_db
def test_reject_requires_non_empty_comment(organizations, roles) -> None:
    own, _ = organizations
    membership, _ = create_member_client(organization=own, role=roles["ADMINISTRATOR"], username="admin-reject-empty")
    concept = make_concept(code="REJECT_EMPTY", organization=own, status="SUGGESTED")

    with pytest.raises(ValueError, match="comment"):
        OntologyContextService(own).reject(concept.id, actor=membership.user, comment="  ")

    concept.refresh_from_db()
    assert concept.status == "SUGGESTED"
    assert not ApprovalRecord.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_state_and_both_audit_records_are_committed_together(organizations, roles, monkeypatch) -> None:
    own, _ = organizations
    membership, _ = create_member_client(organization=own, role=roles["ADMINISTRATOR"], username="admin-atomic")
    concept = make_concept(code="ATOMIC", organization=own, status="SUGGESTED")

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(AuditLog.objects, "create", fail_audit)
    with pytest.raises(RuntimeError, match="audit storage failed"):
        with transaction.atomic():
            OntologyContextService(own).approve(concept.id, actor=membership.user)

    concept.refresh_from_db()
    assert concept.status == "SUGGESTED"
    assert not ApprovalRecord.objects.exists()


@pytest.mark.django_db
def test_generic_audit_primitive_rejects_blank_rejection_before_writes(organizations, roles) -> None:
    own, _ = organizations
    membership, _ = create_member_client(
        organization=own, role=roles["ADMINISTRATOR"], username="audit-direct-reject"
    )

    with pytest.raises(ValueError, match="comment"):
        record_review_transition(
            organization=own,
            object_type="future.Content",
            object_id=uuid.uuid4(),
            action="REJECT",
            status="REJECTED",
            object_version=1,
            actor=membership.user,
            comment="  ",
        )

    assert not ApprovalRecord.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_generic_audit_event_requires_authorized_human_actor(organizations, roles):
    own, other = organizations
    valid, _ = create_member_client(
        organization=own,
        role=roles["ADMINISTRATOR"],
        username="audit-event-valid",
    )
    foreign, _ = create_member_client(
        organization=other,
        role=roles["ADMINISTRATOR"],
        username="audit-event-foreign",
    )
    values = {
        "organization": own,
        "object_type": "sources.RetentionCleanup",
        "object_id": uuid.uuid4(),
        "action": "ARCHIVE",
        "status": "COMPLETED",
        "object_version": 1,
        "required_permission": PermissionCode.SOURCES_MANAGE,
    }

    with pytest.raises(PermissionDenied):
        record_audit_event(**values, actor=None)
    with pytest.raises(PermissionDenied):
        record_audit_event(**values, actor=foreign.user)

    event = record_audit_event(**values, actor=valid.user)
    assert event.organization == own
    assert event.actor == valid.user
    assert AuditLog.objects.count() == 1


@pytest.mark.django_db
def test_system_audit_event_requires_owned_retention_attempt(organizations):
    own, other = organizations
    job = JobService.create(
        organization=own,
        job_type=Job.Type.RETENTION_CLEANUP,
        input_snapshot={"policy_version": "test"},
        idempotency_key="system-audit-retention",
        created_by=None,
    )
    claimed = JobService.claim(
        worker_id="audit-test-worker",
        job_id=job.id,
        job_type=Job.Type.RETENTION_CLEANUP,
    )
    values = {
        "job_id": job.id,
        "claim_token": claimed.claim_token,
        "object_type": "sources.RetentionCleanup",
        "object_id": own.id,
        "action": "ARCHIVE",
        "status": "COMPLETED",
        "object_version": 1,
    }

    with pytest.raises(PermissionDenied):
        record_system_audit_event(organization=other, **values)

    event = record_system_audit_event(organization=own, **values)
    assert event.organization == own
    assert event.actor is None
