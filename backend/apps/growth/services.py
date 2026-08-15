from django.db import transaction

from integrations.platforms.manual_fake import ManualPackageFakeConnector, ManualPackageReceipt

from .models import (
    CRMHandoff,
    ChannelPackage,
    FieldProvenance,
    FollowUp,
    OpportunityReview,
    OutreachDraft,
    TargetAccount,
)


class PackageReviewRequired(RuntimeError):
    pass


class OpportunityHandoffBlocked(RuntimeError):
    pass


@transaction.atomic
def add_to_follow_up(*, account: TargetAccount) -> tuple[FollowUp, bool]:
    return FollowUp.objects.get_or_create(organization=account.organization, account=account)


@transaction.atomic
def create_outreach_draft(*, account: TargetAccount) -> OutreachDraft:
    return OutreachDraft.objects.create(
        organization=account.organization,
        account=account,
        english_draft=(
            f"Hello {account.name} team, may I share a short manufacturing capability summary "
            "for your review?"
        ),
        chinese_explanation="仅建议询问对方是否愿意查看能力摘要；没有声称对方已经采购，也不会自动发送。",
    )


@transaction.atomic
def record_opportunity_review(*, account: TargetAccount, reviewer, decision: str) -> OpportunityReview:
    signal = account.intent_signals.order_by("-observed_at", "-id").first()
    if signal is None:
        raise OpportunityHandoffBlocked("该公司还没有可审核的采购证据。")
    labels = {
        OpportunityReview.Decision.PRIORITIZE: "人工确认为优先跟进",
        OpportunityReview.Decision.OBSERVE: "人工决定继续观察",
        OpportunityReview.Decision.PROCESSED: "人工标记为已处理",
    }
    return OpportunityReview.objects.create(
        organization=account.organization,
        account=account,
        signal=signal,
        decision=decision,
        reason=labels[decision],
        original_confidence=signal.confidence,
        original_score_breakdown=signal.score_breakdown,
        reviewer=reviewer,
    )


@transaction.atomic
def create_mock_crm_handoff(*, account: TargetAccount, draft: OutreachDraft, reviewer) -> tuple[CRMHandoff, bool]:
    review = account.opportunity_reviews.order_by("-created_at", "-id").first()
    if review is None or review.decision != OpportunityReview.Decision.PRIORITIZE:
        raise OpportunityHandoffBlocked("请先人工确认该机会为优先跟进。")
    signal = review.signal
    coverage = int((signal.score_breakdown or {}).get("evidence_coverage", 0))
    envelope = signal.evidence_envelope or {}
    if coverage < 15:
        raise OpportunityHandoffBlocked("证据覆盖不足，暂时只能继续观察。")
    if not signal.content_hash or not signal.source_url or not signal.evidence_text:
        raise OpportunityHandoffBlocked("原始证据不完整，暂时不能交给 CRM。")
    if draft.account_id != account.id or draft.organization_id != account.organization_id:
        raise OpportunityHandoffBlocked("联系草稿与当前客户不匹配。")

    if draft.status != OutreachDraft.Status.APPROVED:
        draft.status = OutreachDraft.Status.APPROVED
        draft.save(update_fields=["status", "updated_at"])
    payload = {
        "candidate": {
            "id": str(account.id),
            "name": account.name,
            "country": account.country,
            "industry": account.industry,
            "website": account.website,
        },
        "review": {
            "id": str(review.id),
            "decision": review.decision,
            "reason": review.reason,
            "original_confidence": review.original_confidence,
            "original_score_breakdown": review.original_score_breakdown,
        },
        "source_evidence": [{
            "url": signal.source_url,
            "content": signal.evidence_text,
            "content_hash": signal.content_hash,
            "source_type": envelope.get("source_type", ""),
        }],
        "outreach_suggestion": {
            "english": draft.english_draft,
            "chinese_explanation": draft.chinese_explanation,
            "delivery": "NEVER_SENT",
        },
        "suggested_next_question": "请先核实采购范围、数量、时间与技术要求，再决定是否联系。",
    }
    return CRMHandoff.objects.get_or_create(
        organization=account.organization,
        review=review,
        defaults={
            "draft": draft,
            "connector": "MOCK_CRM",
            "status": "RECORDED",
            "payload_snapshot": payload,
            "created_by": reviewer,
        },
    )


@transaction.atomic
def approve_channel_package(*, package: ChannelPackage) -> ChannelPackage:
    if package.status != "APPROVED":
        package.status = "APPROVED"
        package.save(update_fields=["status", "updated_at"])
    return package


def export_manual_channel_package(*, package: ChannelPackage) -> ManualPackageReceipt:
    if package.status != "APPROVED":
        raise PackageReviewRequired("Channel package requires human approval before export.")
    return ManualPackageFakeConnector().build_package(
        channel=package.channel,
        payload=package.payload,
    )


@transaction.atomic
def verify_company_fact(*, fact: FieldProvenance) -> FieldProvenance:
    if fact.verification_status != "VERIFIED":
        fact.verification_status = "VERIFIED"
        fact.save(update_fields=["verification_status", "updated_at"])
    return fact
