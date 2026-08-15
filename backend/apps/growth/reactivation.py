from django.db import transaction

from .models import AccountFunnelEvent, OutreachDraft, ReactivationRecord, TargetAccount


class ReactivationBlocked(RuntimeError):
    code = "REACTIVATION_BLOCKED"


class LegalRelationshipRequired(ReactivationBlocked):
    code = "LEGAL_RELATIONSHIP_REQUIRED"


class ReactivationEvidenceInsufficient(ReactivationBlocked):
    code = "REACTIVATION_EVIDENCE_INSUFFICIENT"


def tier_for_account(account: TargetAccount) -> str:
    signal = account.intent_signals.order_by("-observed_at", "-id").first()
    if signal is None:
        return ReactivationRecord.Tier.OBSERVATION
    if not signal.is_demo and (signal.evidence_envelope or {}).get("review_status") != "APPROVED":
        return ReactivationRecord.Tier.OBSERVATION
    score = signal.score_breakdown or {}
    coverage = int(score.get("evidence_coverage", 0))
    icp_fit = int(score.get("icp_fit", 0))
    intent = int(score.get("intent_strength", 0))
    if signal.confidence >= 80 and coverage >= 15 and icp_fit >= 15 and intent >= 15:
        return ReactivationRecord.Tier.STRATEGIC
    if signal.confidence >= 60 and coverage >= 15 and icp_fit >= 15:
        return ReactivationRecord.Tier.NURTURE
    return ReactivationRecord.Tier.OBSERVATION


def _event(record, event_type, actor, payload=None):
    return AccountFunnelEvent.objects.get_or_create(
        organization=record.organization,
        reactivation=record,
        event_type=event_type,
        defaults={
            "account": record.account,
            "actor": actor,
            "payload": payload or {},
        },
    )[0]


@transaction.atomic
def select_for_reactivation(*, account, actor, relationship_source, last_interacted_at,
                            interaction_summary, relationship_confirmed):
    if not relationship_confirmed:
        raise LegalRelationshipRequired("A confirmed existing relationship or legally owned list is required.")
    record, created = ReactivationRecord.objects.update_or_create(
        organization=account.organization,
        account=account,
        defaults={
            "relationship_source": relationship_source,
            "last_interacted_at": last_interacted_at,
            "interaction_summary": interaction_summary,
            "relationship_confirmed": True,
            "tier": tier_for_account(account),
            "selected_by": actor,
            "is_demo": account.is_demo,
        },
    )
    _event(record, AccountFunnelEvent.EventType.REACTIVATION_SELECTED, actor, {
        "relationship_source": relationship_source,
    })
    return record, created


@transaction.atomic
def create_reactivation_draft(*, record, actor):
    if record.tier == ReactivationRecord.Tier.OBSERVATION:
        raise ReactivationEvidenceInsufficient("Complete account evidence before creating outreach.")
    if record.draft_id:
        return record.draft, False
    draft = OutreachDraft.objects.create(
        organization=record.organization,
        account=record.account,
        english_draft=(
            f"Hello {record.account.name} team, we are following up on our previous interaction: "
            f'"{record.interaction_summary}" Would a current manufacturing capability summary '
            f"for {record.account.industry or 'your industry'} be useful for a manual review?"
        ),
        chinese_explanation=(
            "草稿只引用已保存的历史互动和公司行业；没有声称对方正在采购，没有编造联系人或案例，"
            "必须人工审核后再决定是否手工发送。"
        ),
    )
    record.draft = draft
    record.status = ReactivationRecord.Status.DRAFTED
    record.save(update_fields=["draft", "status", "updated_at"])
    _event(record, AccountFunnelEvent.EventType.REACTIVATION_DRAFTED, actor, {
        "draft_id": str(draft.id), "delivery": "NEVER_SENT",
    })
    return draft, True


@transaction.atomic
def approve_reactivation_draft(*, record, actor):
    if not record.draft_id:
        raise ReactivationBlocked("Generate and review a draft before approval.")
    if record.draft.status != OutreachDraft.Status.APPROVED:
        record.draft.status = OutreachDraft.Status.APPROVED
        record.draft.save(update_fields=["status", "updated_at"])
    record.status = ReactivationRecord.Status.APPROVED
    record.save(update_fields=["status", "updated_at"])
    _event(record, AccountFunnelEvent.EventType.REACTIVATION_APPROVED, actor, {
        "draft_id": str(record.draft_id), "delivery": "NEVER_SENT",
    })
    return record


def reactivation_payload(record):
    signal = record.account.intent_signals.order_by("-observed_at", "-id").first()
    tier_actions = {
        ReactivationRecord.Tier.STRATEGIC: "Prepare a human-reviewed reactivation draft",
        ReactivationRecord.Tier.NURTURE: "Prepare a human-reviewed reactivation draft",
        ReactivationRecord.Tier.OBSERVATION: "Complete account evidence before outreach",
    }
    return {
        "id": str(record.id),
        "account_id": str(record.account_id),
        "account_name": record.account.name,
        "industry": record.account.industry,
        "relationship_source": record.relationship_source,
        "last_interacted_at": record.last_interacted_at,
        "interaction_summary": record.interaction_summary,
        "tier": record.tier,
        "status": record.status,
        "is_demo": record.is_demo,
        "why_reactivate": "Existing lawful relationship plus saved account context",
        "recommended_action": tier_actions[record.tier],
        "evidence": signal.evidence_text if signal else "No verified recent signal saved",
        "risk": (
            "Evidence is insufficient; do not contact until facts are completed"
            if record.tier == ReactivationRecord.Tier.OBSERVATION
            else "Historical context may be stale; verify before any manual contact"
        ),
        "draft": ({
            "id": str(record.draft_id),
            "english_draft": record.draft.english_draft,
            "chinese_explanation": record.draft.chinese_explanation,
            "status": record.draft.status,
        } if record.draft_id else None),
        "events": [{
            "event_type": event.event_type,
            "created_at": event.created_at,
            "delivery": event.payload.get("delivery", "NEVER_SENT"),
        } for event in record.events.all()],
        "delivery": "NEVER_SENT",
    }
