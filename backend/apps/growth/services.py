import json
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace

from django.db import transaction

from apps.content.models import PlatformContent
from apps.content.services import content_is_consistent
from integrations.platforms.manual_fake import ManualPackageFakeConnector, ManualPackageReceipt
from apps.ai.provider_config import resolve_product_ai
from apps.ai.services import BudgetedAIProvider
from apps.common.tenancy import tenant_atomic
from apps.knowledge.agent_context import validate_external_output

from .ai_disclosure import ai_fallback_metadata, ai_success_metadata
from .models import (
    CRMHandoff,
    ChannelPackage,
    FieldProvenance,
    FollowUp,
    OpportunityReview,
    OutreachDraft,
    TargetAccount,
)

logger = logging.getLogger(__name__)


class PackageReviewRequired(RuntimeError):
    pass


class ChannelPackagePreparationBlocked(RuntimeError):
    pass


class ChannelPackageBatchInvalid(RuntimeError):
    pass


SUPPORTED_PUBLISH_CHANNELS = {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"}


def _verified_fact_evidence(content: PlatformContent) -> list[dict[str, object]]:
    raw_facts = content.master_content.ai_run.input_snapshot.get("verified_product_facts")
    if not isinstance(raw_facts, list):
        return []
    evidence = []
    for raw in raw_facts[:50]:
        if not isinstance(raw, dict):
            continue
        required = (
            "fact_id", "field_name", "value", "source_filename", "source_excerpt",
        )
        if not all(isinstance(raw.get(key), str) and raw[key].strip() for key in required):
            continue
        page = raw.get("source_page")
        evidence.append({
            "fact_id": raw["fact_id"][:36],
            "field_name": raw["field_name"][:100],
            "value": raw["value"][:500],
            "source_filename": raw["source_filename"][:255],
            "source_page": page if isinstance(page, int) and page > 0 else None,
            "source_excerpt": raw["source_excerpt"][:500],
            "is_demo": raw.get("is_demo") is True,
        })
    return evidence


def _safe_asset_references(content: PlatformContent) -> list[dict[str, object]]:
    references = []
    links = content.master_content.brief.asset_links.select_related("asset").order_by("asset_id")
    for link in links[:50]:
        asset = link.asset
        if asset.organization_id != content.organization_id or asset.status != "ACTIVE":
            continue
        references.append({
            "original_filename": asset.original_filename,
            "mime_type": asset.mime_type,
            "size_bytes": asset.size_bytes,
            "checksum": asset.checksum,
        })
    return references


@transaction.atomic
def prepare_channel_package_from_platform_content(
    *, content: PlatformContent,
) -> tuple[ChannelPackage, bool]:
    content = (
        PlatformContent.objects.select_for_update()
        .select_related(
            "organization", "platform", "master_content__brief",
            "master_content__generation_job", "master_content__ai_run",
            "master_content__ai_run__prompt_version", "master_content__previous_version",
            "previous_version",
        )
        .get(pk=content.pk)
    )
    if content.status != PlatformContent.Status.APPROVED:
        raise ChannelPackagePreparationBlocked("只有人工批准的平台内容可以加入发布准备。")
    if PlatformContent.objects.filter(previous_version=content).exists():
        raise ChannelPackagePreparationBlocked("请使用当前最新版平台内容。")
    if not content_is_consistent(content):
        raise ChannelPackagePreparationBlocked("内容来源校验失败，请返回审核中心检查。")
    channel = content.platform.code.upper()
    if channel not in SUPPORTED_PUBLISH_CHANNELS:
        raise ChannelPackagePreparationBlocked("该平台暂未进入一键发布范围。")
    facts = _verified_fact_evidence(content)
    payload = {
        "title": content.payload["title"],
        "body": content.payload["body"],
        "cta": content.payload["cta"],
        "platform_code": channel,
        "source_platform_content_id": str(content.id),
        "source_platform_content_version": content.version,
        "verified_fact_evidence": facts,
        "asset_references": _safe_asset_references(content),
    }
    if content.payload.get("schema_version") == 2:
        payload.update({
            "language": content.payload["language"],
            "landing_page_url": content.payload["landing_page_url"],
            "hashtags": list(content.payload["hashtags"]),
            "evidence_fact_ids": list(content.payload["evidence_fact_ids"]),
        })
    if channel == "TIKTOK" and content.payload.get("schema_version") == 2:
        payload.update({
            "duration_seconds": content.payload["duration_seconds"],
            "aspect_ratio": content.payload["aspect_ratio"],
            "script": content.payload["script"],
            "shot_list": list(content.payload["shot_list"]),
            "voiceover": content.payload["voiceover"],
            "voiceover_language": content.payload["voiceover_language"],
            "subtitles": content.payload["subtitles"],
            "subtitle_language": content.payload["subtitle_language"],
            "utm": "utm_source=tiktok&utm_medium=organic&utm_campaign=manual-review",
        })
    elif channel == "TIKTOK":
        payload.update({
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "script": content.payload["body"],
            "shot_list": [],
            "english_voiceover": content.payload["body"],
            "chinese_subtitles": "待人工补充中文字幕，批准前不得发布。",
            "hashtags": [],
            "utm": "utm_source=tiktok&utm_medium=organic&utm_campaign=manual-review",
        })
    package, created = ChannelPackage.objects.get_or_create(
        organization=content.organization,
        source_platform_content=content,
        defaults={
            "channel": channel,
            "payload": payload,
            "status": "AWAITING_REVIEW",
            "is_demo": content.master_content.ai_run.provider.lower() == "fake"
            or any(item["is_demo"] for item in facts),
        },
    )
    _link_channel_package_to_mission(package)
    return package, created


def _link_channel_package_to_mission(package) -> None:
    try:
        from .mission_services import link_mission_entity
        from .models import MissionEntityLink

        link = MissionEntityLink.objects.filter(
            organization=package.organization,
            entity_type=MissionEntityLink.EntityType.PLATFORM_CONTENT,
            entity_id=package.source_platform_content_id,
        ).first()
        if link is not None:
            link_mission_entity(
                mission=link.mission,
                entity=package,
                lane=MissionEntityLink.Lane.SOCIAL,
            )
    except Exception:
        logger.exception("Channel package mission linking failed.")


class OpportunityHandoffBlocked(RuntimeError):
    pass


OUTREACH_DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "draft": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["draft", "reasoning"],
}
GROUNDED_OUTREACH_DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "draft": {"type": "string"},
        "reasoning": {"type": "string"},
        "cited_fact_ids": {"type": "array", "items": {"type": "string"}},
        "landing_page_url": {"type": "string"},
    },
    "required": ["draft", "reasoning", "cited_fact_ids", "landing_page_url"],
}


def _outreach_draft_text(account: TargetAccount) -> tuple[str, dict]:
    runtime = resolve_product_ai(account.organization)
    if not runtime.real_requests_enabled:
        return _template_outreach_draft(account), ai_fallback_metadata(
            runtime.provider_code, runtime.model, "real AI disabled"
        )
    signal = account.intent_signals.order_by("-observed_at", "-id").first()
    snapshot = {
        "company_name": account.name,
        "country": account.country,
        "industry": account.industry,
        "website": account.website,
        "evidence": signal.evidence_text if signal else "",
    }
    prompt = "Draft a personalized development email using only the supplied facts.\n||INPUT:" + json.dumps(
        snapshot, ensure_ascii=False,
    )
    try:
        provider = BudgetedAIProvider(
            organization=account.organization,
            model=runtime.model,
            provider=runtime.provider,
        )
        result = provider.generate(
            prompt=prompt,
            schema=OUTREACH_DRAFT_SCHEMA,
        )
        return result["draft"], ai_success_metadata(runtime.provider_code, runtime.model)
    except Exception as error:
        return _template_outreach_draft(account), ai_fallback_metadata(
            runtime.provider_code, runtime.model, str(error)
        )


def _template_outreach_draft(account: TargetAccount) -> str:
    return (
        f"Hello {account.name} team, may I share a short manufacturing capability summary "
        "for your review?"
    )


@transaction.atomic
def add_to_follow_up(*, account: TargetAccount) -> tuple[FollowUp, bool]:
    return FollowUp.objects.get_or_create(organization=account.organization, account=account)


@transaction.atomic
def create_outreach_draft(*, account: TargetAccount) -> tuple[OutreachDraft, bool]:
    existing = account.outreach_drafts.order_by("-created_at", "-id").first()
    if existing is not None:
        return existing, False
    draft_text, metadata = _outreach_draft_text(account)
    chinese_explanation = "仅建议询问对方是否愿意查看能力摘要；没有声称对方已经采购，也不会自动发送。"
    if metadata["fallback_used"]:
        chinese_explanation += (
            f"（注意：本次未使用真实 AI，原因：{metadata['fallback_reason']}）"
        )
    return OutreachDraft.objects.create(
        organization=account.organization,
        account=account,
        english_draft=draft_text,
        chinese_explanation=chinese_explanation,
    ), True


@dataclass(frozen=True, repr=False)
class _OutreachDraftCall:
    account_id: object
    account_updated_at: object
    account: object = field(repr=False)
    runtime: object = field(repr=False)
    evidence: str = field(repr=False)
    agent_context: object = field(default=None, repr=False)


def create_outreach_draft_for_tenant(
    *,
    account_id,
    organization_id,
    agent_context=None,
) -> tuple[OutreachDraft, bool]:
    """Resolve tenant configuration, call AI outside a transaction, then finalize."""

    if agent_context is not None and str(agent_context.organization_id) != str(
        organization_id
    ):
        from apps.knowledge.agent_context import KnowledgeContextError

        raise KnowledgeContextError(
            "KNOWLEDGE_CONTEXT_MISMATCH",
            "Knowledge context does not belong to this organization.",
        )

    with tenant_atomic(organization_id):
        account = TargetAccount.objects.select_related("organization").get(
            pk=account_id,
            organization_id=organization_id,
        )
        existing_query = account.outreach_drafts.filter(organization_id=organization_id)
        if agent_context is not None:
            existing_query = existing_query.filter(
                knowledge_context_snapshot_id=agent_context.snapshot_id
            )
        existing = existing_query.order_by("-created_at", "-id").first()
        if existing is not None:
            return existing, False
        signal = account.intent_signals.filter(
            organization_id=organization_id,
        ).order_by("-observed_at", "-id").first()
        runtime = resolve_product_ai(account.organization)
        frozen = SimpleNamespace(
            name=account.name,
            country=account.country,
            industry=account.industry,
            website=account.website,
        )
        call = _OutreachDraftCall(
            account_id=account.id,
            account_updated_at=account.updated_at,
            account=frozen,
            runtime=runtime,
            evidence=signal.evidence_text if signal else "",
            agent_context=agent_context,
        )

    cited_fact_ids: list[str] = []
    if not call.runtime.real_requests_enabled:
        grounded = (
            _grounded_outreach_draft(call.account, call.evidence, call.agent_context)
            if call.agent_context is not None
            else None
        )
        draft_text = (
            grounded["draft"] if grounded is not None else _template_outreach_draft(call.account)
        )
        if grounded is not None:
            cited_fact_ids = list(grounded["cited_fact_ids"])
        metadata = ai_fallback_metadata(
            call.runtime.provider_code,
            call.runtime.model,
            "real AI disabled",
        )
    else:
        target_evidence = {
            "company_name": call.account.name,
            "country": call.account.country,
            "industry": call.account.industry,
            "website": call.account.website,
            "evidence": call.evidence,
        }
        snapshot = (
            {
                "seller_context": call.agent_context.to_dict(),
                "target_company_evidence": target_evidence,
            }
            if call.agent_context is not None
            else target_evidence
        )
        prompt = (
            "Draft a personalized development email using only the supplied facts.\n"
            "||INPUT:" + json.dumps(snapshot, ensure_ascii=False)
        )
        try:
            provider = BudgetedAIProvider(
                organization_id=organization_id,
                model=call.runtime.model,
                provider=call.runtime.provider,
            )
            result = provider.generate(
                prompt=prompt,
                schema=(
                    GROUNDED_OUTREACH_DRAFT_SCHEMA
                    if call.agent_context is not None
                    else OUTREACH_DRAFT_SCHEMA
                ),
            )
            if call.agent_context is not None:
                validate_external_output(result, context=call.agent_context)
                cited_fact_ids = list(result["cited_fact_ids"])
            draft_text = result["draft"]
            metadata = ai_success_metadata(
                call.runtime.provider_code,
                call.runtime.model,
            )
        except Exception:
            grounded = (
                _grounded_outreach_draft(call.account, call.evidence, call.agent_context)
                if call.agent_context is not None
                else None
            )
            draft_text = (
                grounded["draft"]
                if grounded is not None
                else _template_outreach_draft(call.account)
            )
            if grounded is not None:
                cited_fact_ids = list(grounded["cited_fact_ids"])
            metadata = ai_fallback_metadata(
                call.runtime.provider_code,
                call.runtime.model,
                "provider generation failed",
            )

    with tenant_atomic(organization_id):
        locked = TargetAccount.objects.select_for_update().get(
            pk=call.account_id,
            organization_id=organization_id,
        )
        if locked.updated_at != call.account_updated_at:
            raise RuntimeError("Account changed during outreach draft generation.")
        existing_query = locked.outreach_drafts.filter(organization_id=organization_id)
        if call.agent_context is not None:
            existing_query = existing_query.filter(
                knowledge_context_snapshot_id=call.agent_context.snapshot_id
            )
        existing = existing_query.order_by("-created_at", "-id").first()
        if existing is not None:
            return existing, False
        explanation = "Human review is required before this draft can be sent."
        if call.agent_context is not None:
            explanation += " Public fact IDs: " + ", ".join(
                sorted(cited_fact_ids)
            )
        if metadata["fallback_used"]:
            explanation += " AI generation was unavailable; a safe template was used."
        return OutreachDraft.objects.create(
            organization_id=organization_id,
            account=locked,
            knowledge_context_snapshot_id=(
                call.agent_context.snapshot_id if call.agent_context is not None else None
            ),
            english_draft=draft_text,
            chinese_explanation=explanation,
        ), True


def _grounded_outreach_draft(account, evidence, agent_context) -> dict:
    context = agent_context.to_dict()
    seller = context["seller"]
    company = seller["company_profile"]
    claims = seller["public_claims"]
    pages = context["website_pages"]
    if not claims:
        from apps.knowledge.agent_context import KnowledgeContextError

        raise KnowledgeContextError(
            "PUBLIC_CLAIM_BLOCKED",
            "At least one cited public claim is required for outreach.",
        )
    page = pages[0]
    landing_page_url = page.get("primary_cta", {}).get("url") or page["canonical_url"]
    claim = claims[0]
    claim_text = json.dumps(claim["value"], ensure_ascii=False, sort_keys=True)
    brand = company.get("brand_name") or company.get("legal_name_en") or "our team"
    draft = (
        f"Hello {account.name} team, {brand} supports relevant manufacturing work with "
        f"this documented public capability: {claim_text}. Based on your public profile"
        f"{f' ({evidence})' if evidence else ''}, would a short review be useful? "
        f"{landing_page_url}"
    )
    output = {
        "draft": draft,
        "reasoning": "Uses one public seller claim and separately supplied target evidence.",
        "cited_fact_ids": [claim["fact_id"]],
        "landing_page_url": landing_page_url,
    }
    validate_external_output(output, context=agent_context)
    return output


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


@transaction.atomic
def approve_channel_package_batch(*, organization, package_ids) -> list[ChannelPackage]:
    unique_ids = list(dict.fromkeys(package_ids))
    if len(unique_ids) != 4:
        raise ChannelPackageBatchInvalid("请选择四个不同渠道的内容包。")
    packages = list(
        ChannelPackage.objects.select_for_update()
        .filter(organization=organization, id__in=unique_ids)
        .order_by("channel", "id")
    )
    if len(packages) != 4 or {package.channel for package in packages} != SUPPORTED_PUBLISH_CHANNELS:
        raise ChannelPackageBatchInvalid("内容包必须来自当前组织并覆盖四个支持渠道。")
    for package in packages:
        approve_channel_package(package=package)
    return packages


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
