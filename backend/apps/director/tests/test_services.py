from datetime import timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.audit.models import AuditLog, ReviewAction
from apps.director.models import DirectorDecision, DirectorProposal
from apps.director.services import (
    DirectorIdempotencyConflict,
    DirectorService,
    DirectorStateConflict,
    DirectorVersionConflict,
)
from apps.identity.models import Membership, Organization, Role


@pytest.fixture
def organization():
    return Organization.objects.create(name="Director Own", slug="director-service-own")


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Director Other", slug="director-service-other")


@pytest.fixture
def reviewer(organization):
    user = get_user_model().objects.create_user(username="director-reviewer")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_reviewer(),
    )
    return user


@pytest.fixture
def read_only_user(organization):
    user = get_user_model().objects.create_user(username="director-reader")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_read_only(),
    )
    return user


def proposal_values(**overrides):
    values = {
        "proposal_type": DirectorProposal.ProposalType.PROMOTION_PLAN,
        "title_zh": "建议批准德国市场推广计划",
        "summary_zh": "基于已确认的产品能力和市场证据。",
        "reason_snapshot": {
            "evidence_count": 3,
            "authorization": "Bearer sk-director-secret-12345678",
        },
        "action_reference": {"kind": "campaign_draft", "id": "draft-1"},
        "priority": 80,
        "idempotency_key": "director-proposal-1",
    }
    values.update(overrides)
    return values


@pytest.fixture
def proposal(organization):
    return DirectorService.propose(organization=organization, **proposal_values())


@pytest.mark.django_db
def test_propose_returns_exact_existing_proposal_for_same_idempotent_payload(organization):
    expires_at = timezone.now() + timedelta(days=2)
    first = DirectorService.propose(
        organization=organization,
        **proposal_values(expires_at=expires_at),
    )
    second = DirectorService.propose(
        organization=organization,
        **proposal_values(expires_at=expires_at),
    )

    assert second.id == first.id
    assert DirectorProposal.objects.count() == 1
    assert first.reason_snapshot == {"evidence_count": 3}


@pytest.mark.django_db
def test_propose_rejects_same_idempotency_key_with_different_payload(organization):
    DirectorService.propose(organization=organization, **proposal_values())

    with pytest.raises(DirectorIdempotencyConflict):
        DirectorService.propose(
            organization=organization,
            **proposal_values(summary_zh="A different proposal intent."),
        )

    assert DirectorProposal.objects.count() == 1


@pytest.mark.django_db
def test_idempotency_key_is_scoped_to_organization(organization, other_organization):
    own = DirectorService.propose(organization=organization, **proposal_values())
    other = DirectorService.propose(
        organization=other_organization,
        **proposal_values(title_zh="Other organization proposal"),
    )

    assert own.id != other.id
    assert DirectorProposal.objects.count() == 2


@pytest.mark.django_db
def test_cross_organization_decision_is_hidden_as_not_found(
    proposal, other_organization, reviewer
):
    with pytest.raises(DirectorProposal.DoesNotExist):
        DirectorService.decide(
            organization=other_organization,
            proposal_id=proposal.id,
            expected_version=proposal.version,
            action=DirectorDecision.Action.APPROVE,
            actor=reviewer,
        )


@pytest.mark.django_db
def test_stale_decision_cannot_approve(proposal, reviewer):
    with pytest.raises(DirectorVersionConflict):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=proposal.version + 1,
            action=DirectorDecision.Action.APPROVE,
            actor=reviewer,
        )

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert not DirectorDecision.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action",
    [DirectorDecision.Action.REJECT, DirectorDecision.Action.REQUEST_ADJUSTMENT],
)
def test_reject_and_adjustment_require_non_blank_comment(proposal, reviewer, action):
    with pytest.raises(ValidationError, match="comment"):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=proposal.version,
            action=action,
            actor=reviewer,
            comment="  ",
        )

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert not DirectorDecision.objects.exists()


@pytest.mark.django_db
def test_expired_proposal_cannot_be_decided(organization, reviewer):
    proposal = DirectorService.propose(
        organization=organization,
        **proposal_values(expires_at=timezone.now() - timedelta(seconds=1)),
    )

    with pytest.raises(DirectorStateConflict, match="expired"):
        DirectorService.decide(
            organization=organization,
            proposal_id=proposal.id,
            expected_version=proposal.version,
            action=DirectorDecision.Action.APPROVE,
            actor=reviewer,
        )

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert not DirectorDecision.objects.exists()


@pytest.mark.django_db
def test_decision_requires_current_organization_permission(proposal, read_only_user):
    with pytest.raises(PermissionDenied):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=proposal.version,
            action=DirectorDecision.Action.APPROVE,
            actor=read_only_user,
        )

    assert not DirectorDecision.objects.exists()


@pytest.mark.django_db
def test_decision_updates_once_and_appends_one_decision_and_audit(proposal, reviewer):
    original_version = proposal.version

    decided = DirectorService.decide(
        organization=proposal.organization,
        proposal_id=proposal.id,
        expected_version=original_version,
        action=DirectorDecision.Action.APPROVE,
        actor=reviewer,
    )

    decision = DirectorDecision.objects.get()
    audit = AuditLog.objects.get()
    assert decided.status == DirectorProposal.Status.APPROVED
    assert decided.version == original_version + 1
    assert decision.proposal_version == original_version
    assert decision.action == DirectorDecision.Action.APPROVE
    assert audit.organization == proposal.organization
    assert audit.object_type == "director.DirectorProposal"
    assert audit.object_id == proposal.id
    assert audit.action == ReviewAction.APPROVE
    assert audit.status == DirectorProposal.Status.APPROVED
    assert audit.object_version == original_version + 1
    assert audit.before_metadata == {
        "status": DirectorProposal.Status.PENDING,
        "version": original_version,
    }
    assert audit.after_metadata == {
        "status": DirectorProposal.Status.APPROVED,
        "version": original_version + 1,
    }

    with pytest.raises(DirectorVersionConflict):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=original_version,
            action=DirectorDecision.Action.REJECT,
            actor=reviewer,
            comment="No longer approve.",
        )
    assert DirectorDecision.objects.count() == 1
    assert AuditLog.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_decision_and_state_roll_back_when_audit_append_fails(
    proposal, reviewer, monkeypatch
):
    def fail_audit(**kwargs):
        raise RuntimeError("audit append failed")

    monkeypatch.setattr("apps.director.services.record_audit_event", fail_audit)

    with pytest.raises(RuntimeError, match="audit append failed"):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=proposal.version,
            action=DirectorDecision.Action.APPROVE,
            actor=reviewer,
        )

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert proposal.version == 1
    assert not DirectorDecision.objects.exists()


@pytest.mark.django_db
def test_supersede_marks_original_and_appends_system_audit(
    organization, other_organization
):
    original = DirectorService.propose(organization=organization, **proposal_values())
    replacement = DirectorService.propose(
        organization=organization,
        **proposal_values(
            title_zh="Replacement proposal", idempotency_key="director-proposal-2"
        ),
    )

    result = DirectorService.supersede(
        organization=organization,
        proposal_id=original.id,
        replacement_id=replacement.id,
    )

    audit = AuditLog.objects.get()
    assert result.status == DirectorProposal.Status.SUPERSEDED
    assert result.version == 2
    assert audit.action == ReviewAction.SUPERSEDE
    assert audit.actor is None
    assert audit.after_metadata["replacement_id"] == str(replacement.id)

    with pytest.raises(DirectorProposal.DoesNotExist):
        DirectorService.supersede(
            organization=other_organization,
            proposal_id=replacement.id,
            replacement_id=original.id,
        )


@pytest.mark.django_db
def test_proposal_state_and_version_cannot_bypass_director_service(proposal):
    proposal.status = DirectorProposal.Status.APPROVED
    proposal.version += 1
    with pytest.raises(ValidationError, match="DirectorService"):
        proposal.save(update_fields=["status", "version", "updated_at"])
    with pytest.raises(ValidationError, match="DirectorService"):
        DirectorProposal.objects.filter(pk=proposal.id).update(
            status=DirectorProposal.Status.APPROVED
        )
    with pytest.raises(ValidationError, match="DirectorService"):
        DirectorProposal.objects.bulk_update([proposal], ["status", "version"])

    persisted = DirectorProposal.objects.get(pk=proposal.id)
    assert persisted.status == DirectorProposal.Status.PENDING
    assert persisted.version == 1
    assert not DirectorDecision.objects.exists()
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("expired_side", ["original", "replacement"])
def test_supersede_rejects_expired_proposals(organization, expired_side):
    past = timezone.now() - timedelta(seconds=1)
    original = DirectorService.propose(
        organization=organization,
        **proposal_values(
            expires_at=past if expired_side == "original" else None,
        ),
    )
    replacement = DirectorService.propose(
        organization=organization,
        **proposal_values(
            title_zh="Replacement proposal",
            expires_at=past if expired_side == "replacement" else None,
            idempotency_key="director-proposal-2",
        ),
    )

    with pytest.raises(DirectorStateConflict, match="expired"):
        DirectorService.supersede(
            organization=organization,
            proposal_id=original.id,
            replacement_id=replacement.id,
        )

    original.refresh_from_db()
    assert original.status == DirectorProposal.Status.PENDING
    assert not AuditLog.objects.exists()


@pytest.mark.django_db
def test_supersede_requires_same_proposal_type(organization):
    original = DirectorService.propose(organization=organization, **proposal_values())
    replacement = DirectorService.propose(
        organization=organization,
        **proposal_values(
            proposal_type=DirectorProposal.ProposalType.COST_APPROVAL,
            title_zh="Unrelated replacement",
            idempotency_key="director-proposal-2",
        ),
    )

    with pytest.raises(ValidationError, match="type"):
        DirectorService.supersede(
            organization=organization,
            proposal_id=original.id,
            replacement_id=replacement.id,
        )

    original.refresh_from_db()
    assert original.status == DirectorProposal.Status.PENDING
    assert not AuditLog.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_director_audit_action_migration_preserves_existing_rows():
    before = ("audit", "0003_auditlog_actor_nullable")
    after = ("audit", "0004_expand_director_actions")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([before])
        old_apps = executor.loader.project_state([before]).apps
        organization_model = old_apps.get_model("identity", "Organization")
        user_model = old_apps.get_model("auth", "User")
        audit_model = old_apps.get_model("audit", "AuditLog")
        organization = organization_model.objects.create(
            name="Audit Migration", slug="director-audit-migration"
        )
        actor = user_model.objects.create(username="director-audit-migration")
        object_id = uuid.uuid4()
        audit_model.objects.create(
            organization=organization,
            object_type="legacy.Record",
            object_id=object_id,
            action="APPROVE",
            status="APPROVED",
            object_version=1,
            actor=actor,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        migrated_audit_model = executor.loader.project_state([after]).apps.get_model(
            "audit", "AuditLog"
        )
        row = migrated_audit_model.objects.get(object_id=object_id)
        action_field = migrated_audit_model._meta.get_field("action")
        assert row.action == "APPROVE"
        assert action_field.max_length == 24
        assert {value for value, _ in action_field.choices} >= {
            "REQUEST_ADJUSTMENT",
            "SUPERSEDE",
        }
    finally:
        MigrationExecutor(connection).migrate(latest)
