import uuid

import pytest
from django.db import transaction

from apps.audit.models import ApprovalRecord, AuditLog
from apps.audit.services import record_review_transition
from apps.knowledge.models import KnowledgeConcept, KnowledgeGraphLock
from apps.knowledge.services import OntologyContextService

from apps.knowledge.tests.conftest import create_member_client, make_concept


@pytest.fixture(autouse=True)
def ensure_graph_lock():
    KnowledgeGraphLock.objects.get_or_create(id=1, defaults={"name": "is_a_graph"})


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
