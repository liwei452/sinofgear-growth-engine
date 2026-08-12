import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog, ReviewAction, approval_audit_writes
from apps.audit.services import record_audit_event
from apps.common.security import scrub_secrets
from apps.identity.models import Membership, Role
from apps.identity.permissions import PermissionCode
from apps.identity.services import lock_organization_scope, require_permission

from .models import (
    DirectorDecision,
    DirectorProposal,
    director_proposal_state_writes,
)


class DirectorConflict(ValueError):
    pass


class DirectorIdempotencyConflict(DirectorConflict):
    pass


class DirectorVersionConflict(DirectorConflict):
    pass


class DirectorStateConflict(DirectorConflict):
    pass


_PROPOSAL_NAMESPACE = uuid.UUID("eeceeb0e-f360-4a6e-99b1-88e64c6811e7")
_DECISION_STATUSES = {
    DirectorDecision.Action.APPROVE: DirectorProposal.Status.APPROVED,
    DirectorDecision.Action.REQUEST_ADJUSTMENT:
        DirectorProposal.Status.ADJUSTMENT_REQUESTED,
    DirectorDecision.Action.REJECT: DirectorProposal.Status.REJECTED,
}


def _json_copy(value, *, field_name):
    try:
        encoded = json.dumps(
            scrub_secrets(value), sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as error:
        raise ValidationError({field_name: "Value must be JSON serializable."}) from error
    return json.loads(encoded)


def _proposal_id(*, organization_id, idempotency_key):
    return uuid.uuid5(
        _PROPOSAL_NAMESPACE, f"{organization_id}:{idempotency_key}"
    )


def _proposal_matches(proposal, values):
    return all(getattr(proposal, field) == value for field, value in values.items())


def _lock_decider(*, organization, actor):
    if actor is None:
        raise PermissionDenied("Director decisions require an authorized human actor.")
    try:
        membership = Membership.objects.select_for_update().get(
            user=actor,
            organization=organization,
            status=Membership.Status.ACTIVE,
        )
    except Membership.DoesNotExist as error:
        raise PermissionDenied(
            "Director decisions require an active organization membership."
        ) from error
    membership.role = Role.objects.select_for_update().get(pk=membership.role_id)
    require_permission(
        membership=membership,
        permission=PermissionCode.DIRECTOR_DECIDE,
    )


class DirectorService:
    @staticmethod
    @transaction.atomic
    def propose(
        *,
        organization,
        proposal_type,
        title_zh,
        summary_zh,
        reason_snapshot,
        action_reference,
        priority=50,
        expires_at=None,
        idempotency_key,
    ) -> DirectorProposal:
        organization = lock_organization_scope(organization=organization)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError(
                {"idempotency_key": "Idempotency key must not be blank."}
            )
        key = idempotency_key.strip()
        values = {
            "proposal_type": proposal_type,
            "title_zh": title_zh,
            "summary_zh": summary_zh,
            "reason_snapshot": _json_copy(
                reason_snapshot, field_name="reason_snapshot"
            ),
            "action_reference": _json_copy(
                action_reference, field_name="action_reference"
            ),
            "priority": priority,
            "expires_at": expires_at,
        }
        proposal_id = _proposal_id(
            organization_id=organization.id, idempotency_key=key
        )
        existing = DirectorProposal.objects.select_for_update().filter(
            pk=proposal_id, organization=organization
        ).first()
        if existing is not None:
            if not _proposal_matches(existing, values):
                raise DirectorIdempotencyConflict(
                    "Idempotency key already has a different proposal payload."
                )
            return existing

        proposal = DirectorProposal(
            id=proposal_id,
            organization=organization,
            **values,
        )
        proposal.full_clean()
        proposal.save(force_insert=True)
        return proposal

    @staticmethod
    @transaction.atomic
    def decide(
        *,
        organization,
        proposal_id,
        expected_version,
        action,
        actor,
        comment="",
    ) -> DirectorProposal:
        organization = lock_organization_scope(organization=organization)
        try:
            proposal = DirectorProposal.objects.select_for_update().get(
                pk=proposal_id, organization=organization
            )
        except DirectorProposal.DoesNotExist:
            raise

        _lock_decider(organization=organization, actor=actor)
        if proposal.version != expected_version:
            raise DirectorVersionConflict("Director proposal version is stale.")
        if proposal.status != DirectorProposal.Status.PENDING:
            raise DirectorStateConflict("Director proposal is no longer pending.")
        if proposal.expires_at is not None and proposal.expires_at <= timezone.now():
            raise DirectorStateConflict("Director proposal has expired.")
        if action not in _DECISION_STATUSES:
            raise ValidationError({"action": "Unsupported director decision action."})
        normalized_comment = comment.strip()
        if action in {
            DirectorDecision.Action.REJECT,
            DirectorDecision.Action.REQUEST_ADJUSTMENT,
        } and not normalized_comment:
            raise ValidationError(
                {"comment": "Reject and adjustment decisions require a comment."}
            )

        before = {"status": proposal.status, "version": proposal.version}
        DirectorDecision.objects.create(
            proposal=proposal,
            organization=organization,
            action=action,
            proposal_version=proposal.version,
            actor=actor,
            comment=normalized_comment,
        )
        proposal.status = _DECISION_STATUSES[action]
        proposal.version += 1
        with director_proposal_state_writes():
            proposal.save(update_fields=["status", "version", "updated_at"])
        after = {"status": proposal.status, "version": proposal.version}
        record_audit_event(
            organization=organization,
            object_type="director.DirectorProposal",
            object_id=proposal.id,
            action=action,
            status=proposal.status,
            object_version=proposal.version,
            actor=actor,
            required_permission=PermissionCode.DIRECTOR_DECIDE,
            comment=normalized_comment,
            before_metadata=before,
            after_metadata=after,
        )
        return proposal

    @staticmethod
    @transaction.atomic
    def supersede(*, organization, proposal_id, replacement_id) -> DirectorProposal:
        organization = lock_organization_scope(organization=organization)
        if proposal_id == replacement_id:
            raise ValidationError(
                {"replacement_id": "A proposal cannot supersede itself."}
            )
        proposals = {
            proposal.id: proposal
            for proposal in DirectorProposal.objects.select_for_update()
            .filter(
                organization=organization,
                id__in=[proposal_id, replacement_id],
            )
            .order_by("id")
        }
        try:
            proposal = proposals[proposal_id]
            replacement = proposals[replacement_id]
        except KeyError as error:
            raise DirectorProposal.DoesNotExist from error
        if proposal.status != DirectorProposal.Status.PENDING:
            raise DirectorStateConflict("Only pending proposals may be superseded.")
        if replacement.status != DirectorProposal.Status.PENDING:
            raise DirectorStateConflict("Replacement proposal must be pending.")
        now = timezone.now()
        if proposal.expires_at is not None and proposal.expires_at <= now:
            raise DirectorStateConflict("Original proposal has expired.")
        if replacement.expires_at is not None and replacement.expires_at <= now:
            raise DirectorStateConflict("Replacement proposal has expired.")
        if proposal.proposal_type != replacement.proposal_type:
            raise ValidationError(
                {"replacement_id": "Replacement proposal type must match."}
            )

        before = {"status": proposal.status, "version": proposal.version}
        proposal.status = DirectorProposal.Status.SUPERSEDED
        proposal.version += 1
        with director_proposal_state_writes():
            proposal.save(update_fields=["status", "version", "updated_at"])
        after = {
            "status": proposal.status,
            "version": proposal.version,
            "replacement_id": str(replacement.id),
        }
        with approval_audit_writes():
            AuditLog.objects.create(
                organization=organization,
                object_type="director.DirectorProposal",
                object_id=proposal.id,
                action=ReviewAction.SUPERSEDE,
                status=proposal.status,
                object_version=proposal.version,
                actor=None,
                before_metadata=before,
                after_metadata=after,
            )
        return proposal


__all__ = [
    "DirectorConflict",
    "DirectorIdempotencyConflict",
    "DirectorService",
    "DirectorStateConflict",
    "DirectorVersionConflict",
]
