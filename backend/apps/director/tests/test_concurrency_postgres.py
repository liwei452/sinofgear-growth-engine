import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, transaction

from apps.audit.models import AuditLog
from apps.director.models import DirectorDecision, DirectorProposal
from apps.director.services import (
    DirectorService,
    DirectorStateConflict,
    DirectorVersionConflict,
)
from apps.identity.models import Membership, Organization, Role
from apps.identity.services import lock_organization_scope


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="requires PostgreSQL row-lock semantics",
    ),
]


def _proposal_values(key, *, title="Concurrent proposal"):
    return {
        "proposal_type": DirectorProposal.ProposalType.PROMOTION_PLAN,
        "title_zh": title,
        "summary_zh": "PostgreSQL concurrency contract.",
        "reason_snapshot": {"evidence_count": 1},
        "action_reference": {"kind": "campaign_draft", "id": key},
        "idempotency_key": key,
    }


@pytest.fixture
def concurrency_context():
    organization = Organization.objects.create(
        name="Director Concurrent", slug="director-concurrent"
    )
    role = Role.objects.create_reviewer()
    user_model = get_user_model()
    first = user_model.objects.create_user(username="director-concurrent-first")
    second = user_model.objects.create_user(username="director-concurrent-second")
    Membership.objects.create(user=first, organization=organization, role=role)
    Membership.objects.create(user=second, organization=organization, role=role)
    proposal = DirectorService.propose(
        organization=organization, **_proposal_values("concurrent-original")
    )
    replacement = DirectorService.propose(
        organization=organization,
        **_proposal_values("concurrent-replacement", title="Replacement"),
    )
    return organization, role, first, second, proposal, replacement


def _run_concurrently(*operations):
    barrier = threading.Barrier(len(operations))

    def invoke(operation):
        close_old_connections()
        barrier.wait(timeout=10)
        try:
            return ("ok", operation())
        except Exception as error:  # returned for exact cross-thread assertions
            return ("error", error)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=len(operations)) as executor:
        return list(executor.map(invoke, operations))


def _signal_before_organization_lock(monkeypatch, attempted_lock):
    import apps.director.services as director_services

    real_lock = director_services.lock_organization_scope

    def signaling_lock(*, organization):
        attempted_lock.set()
        return real_lock(organization=organization)

    monkeypatch.setattr(
        director_services, "lock_organization_scope", signaling_lock
    )


def test_concurrent_decisions_have_one_coherent_winner(concurrency_context):
    organization, _, first, second, proposal, _ = concurrency_context

    def decide(actor, action, comment=""):
        return lambda: DirectorService.decide(
            organization=organization,
            proposal_id=proposal.id,
            expected_version=1,
            action=action,
            actor=actor,
            comment=comment,
        )

    results = _run_concurrently(
        decide(first, DirectorDecision.Action.APPROVE),
        decide(second, DirectorDecision.Action.REJECT, "Reject concurrently."),
    )

    assert [status for status, _ in results].count("ok") == 1
    errors = [value for status, value in results if status == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], DirectorVersionConflict)
    proposal.refresh_from_db()
    assert proposal.version == 2
    assert proposal.status in {
        DirectorProposal.Status.APPROVED,
        DirectorProposal.Status.REJECTED,
    }
    assert DirectorDecision.objects.filter(proposal=proposal).count() == 1
    assert AuditLog.objects.filter(object_id=proposal.id).count() == 1


def test_concurrent_decide_and_supersede_have_one_coherent_winner(
    concurrency_context,
):
    organization, _, first, second, proposal, replacement = concurrency_context

    results = _run_concurrently(
        lambda: DirectorService.decide(
            organization=organization,
            proposal_id=proposal.id,
            expected_version=1,
            action=DirectorDecision.Action.APPROVE,
            actor=first,
        ),
        lambda: DirectorService.supersede(
            organization=organization,
            proposal_id=proposal.id,
            replacement_id=replacement.id,
            actor=second,
        ),
    )

    assert [status for status, _ in results].count("ok") == 1
    errors = [value for status, value in results if status == "error"]
    assert len(errors) == 1
    assert isinstance(errors[0], (DirectorVersionConflict, DirectorStateConflict))
    proposal.refresh_from_db()
    assert proposal.version == 2
    assert proposal.status in {
        DirectorProposal.Status.APPROVED,
        DirectorProposal.Status.SUPERSEDED,
    }
    expected_decisions = int(proposal.status == DirectorProposal.Status.APPROVED)
    assert DirectorDecision.objects.filter(proposal=proposal).count() == expected_decisions
    assert AuditLog.objects.filter(object_id=proposal.id).count() == 1


def test_membership_revocation_commits_before_waiting_decision(
    concurrency_context, monkeypatch
):
    organization, _, first, _, proposal, _ = concurrency_context
    scope_locked = threading.Event()
    decision_attempted_scope_lock = threading.Event()
    allow_revocation_commit = threading.Event()
    _signal_before_organization_lock(monkeypatch, decision_attempted_scope_lock)

    def revoke():
        close_old_connections()
        try:
            with transaction.atomic():
                locked_organization = lock_organization_scope(
                    organization=organization.id
                )
                membership = Membership.objects.select_for_update().get(user=first)
                scope_locked.set()
                assert allow_revocation_commit.wait(timeout=10)
                membership.status = Membership.Status.INACTIVE
                membership.save(update_fields=["status"])
                return locked_organization.id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        revoke_future = executor.submit(revoke)
        assert scope_locked.wait(timeout=10)
        decide_future = executor.submit(
            DirectorService.decide,
            organization=organization,
            proposal_id=proposal.id,
            expected_version=1,
            action=DirectorDecision.Action.APPROVE,
            actor=first,
        )
        assert decision_attempted_scope_lock.wait(timeout=10)
        allow_revocation_commit.set()
        assert revoke_future.result(timeout=10) == organization.id
        with pytest.raises(PermissionDenied):
            decide_future.result(timeout=10)

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert proposal.version == 1
    assert not DirectorDecision.objects.filter(proposal=proposal).exists()
    assert not AuditLog.objects.filter(object_id=proposal.id).exists()


def test_role_permission_revocation_commits_before_waiting_decision(
    concurrency_context, monkeypatch
):
    organization, role, first, _, proposal, _ = concurrency_context
    scope_locked = threading.Event()
    decision_attempted_scope_lock = threading.Event()
    allow_revocation_commit = threading.Event()
    _signal_before_organization_lock(monkeypatch, decision_attempted_scope_lock)

    def revoke_role_permission():
        close_old_connections()
        try:
            with transaction.atomic():
                lock_organization_scope(organization=organization.id)
                locked_role = Role.objects.select_for_update().get(pk=role.id)
                scope_locked.set()
                assert allow_revocation_commit.wait(timeout=10)
                locked_role.permissions = ["director.read"]
                locked_role.save(update_fields=["permissions"])
                return locked_role.id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        revoke_future = executor.submit(revoke_role_permission)
        assert scope_locked.wait(timeout=10)
        decide_future = executor.submit(
            DirectorService.decide,
            organization=organization,
            proposal_id=proposal.id,
            expected_version=1,
            action=DirectorDecision.Action.APPROVE,
            actor=first,
        )
        assert decision_attempted_scope_lock.wait(timeout=10)
        allow_revocation_commit.set()
        assert revoke_future.result(timeout=10) == role.id
        with pytest.raises(PermissionDenied):
            decide_future.result(timeout=10)

    proposal.refresh_from_db()
    assert proposal.status == DirectorProposal.Status.PENDING
    assert proposal.version == 1
    assert not DirectorDecision.objects.filter(proposal=proposal).exists()
    assert not AuditLog.objects.filter(object_id=proposal.id).exists()
