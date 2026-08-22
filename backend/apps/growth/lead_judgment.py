import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from apps.ai.provider_config import resolve_product_ai
from apps.ai.services import BudgetedAIProvider
from apps.common.tenancy import tenant_atomic

from .ai_disclosure import ai_fallback_metadata, ai_success_metadata
from .grading import grade_candidate


LEAD_JUDGMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "industry": {"type": "string"},
        "uses_gears": {"type": "boolean"},
        "intent": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "grade": {"enum": ["A", "B", "C"]},
        "reason": {"type": "string"},
    },
    "required": ["industry", "uses_gears", "intent", "score", "grade", "reason"],
}


def judge_candidate(candidate, *, website_facts=None) -> dict:
    runtime = resolve_product_ai(candidate.organization)
    if not runtime.real_requests_enabled:
        result = _deterministic_judgment(candidate, website_facts)
        result.update(
            ai_fallback_metadata(runtime.provider_code, runtime.model, "real AI disabled")
        )
        return result

    snapshot = {
        "company_name": candidate.company_name,
        "country": candidate.country,
        "industry": candidate.industry,
        "website": candidate.website,
        "website_title": website_facts.title if website_facts else "",
        "website_text": (website_facts.text_excerpt if website_facts else "")[:2000],
        "gear_terms": list(website_facts.gear_terms) if website_facts else [],
    }
    prompt = "Analyze this company for industrial gear and transmission buyer fit.\n||INPUT:" + json.dumps(
        snapshot, ensure_ascii=False,
    )
    try:
        provider = BudgetedAIProvider(
            organization=candidate.organization,
            model=runtime.model,
            provider=runtime.provider,
        )
        result = provider.generate(
            prompt=prompt,
            schema=LEAD_JUDGMENT_SCHEMA,
        )
        result.update(ai_success_metadata(runtime.provider_code, runtime.model))
        return result
    except Exception as error:
        result = _deterministic_judgment(candidate, website_facts)
        result.update(
            ai_fallback_metadata(runtime.provider_code, runtime.model, str(error))
        )
        return result


@dataclass(frozen=True, repr=False)
class _TenantJudgmentCall:
    organization_id: object
    runtime: object = field(repr=False)
    candidate: object = field(repr=False)
    website_facts: object = field(repr=False)


def judge_candidate_for_tenant(
    candidate_id,
    *,
    organization_id,
    website_facts=None,
    agent_context=None,
) -> dict:
    """Resolve tenant AI configuration before leaving the database transaction."""

    from .models import DiscoveryCandidate
    from apps.knowledge.agent_context import KnowledgeContextError

    if agent_context is not None and str(agent_context.organization_id) != str(
        organization_id
    ):
        raise KnowledgeContextError(
            "KNOWLEDGE_CONTEXT_MISMATCH",
            "Knowledge context does not belong to this organization.",
        )

    with tenant_atomic(organization_id):
        candidate = DiscoveryCandidate.objects.select_related("organization").get(
            pk=candidate_id,
            organization_id=organization_id,
        )
        runtime = resolve_product_ai(candidate.organization)
        frozen_candidate = SimpleNamespace(
            company_name=candidate.company_name,
            country=candidate.country,
            industry=candidate.industry,
            website=candidate.website,
            raw_record=dict(candidate.raw_record or {}),
        )
        call = _TenantJudgmentCall(
            organization_id=organization_id,
            runtime=runtime,
            candidate=frozen_candidate,
            website_facts=website_facts,
        )
    if not call.runtime.real_requests_enabled:
        if agent_context is not None:
            return _deterministic_grounded_judgment(
                call.candidate,
                call.website_facts,
                agent_context,
                provider_code=call.runtime.provider_code,
                model=call.runtime.model,
            )
        result = _deterministic_judgment(call.candidate, call.website_facts)
        result.update(
            ai_fallback_metadata(
                call.runtime.provider_code,
                call.runtime.model,
                "real AI disabled",
            )
        )
        return result

    target_evidence = _target_company_evidence(call.candidate, website_facts)
    if agent_context is None:
        snapshot = target_evidence
        instruction = "Analyze this company for industrial gear and transmission buyer fit."
    else:
        snapshot = {
            "seller_context": agent_context.to_dict(),
            "target_company_evidence": target_evidence,
        }
        instruction = (
            "Judge product, ICP, geography/industry, purchasing-trigger, evidence-strength, "
            "and uncertainty fit. Seller context and target-company evidence are separate; "
            "never treat target evidence as seller capability."
        )
    prompt = instruction + "\n||INPUT:" + json.dumps(snapshot, ensure_ascii=False)
    try:
        provider = BudgetedAIProvider(
            organization_id=organization_id,
            model=call.runtime.model,
            provider=call.runtime.provider,
        )
        result = provider.generate(prompt=prompt, schema=LEAD_JUDGMENT_SCHEMA)
        result.update(
            ai_success_metadata(call.runtime.provider_code, call.runtime.model)
        )
        return result
    except Exception:
        if agent_context is not None:
            return _deterministic_grounded_judgment(
                call.candidate,
                call.website_facts,
                agent_context,
                provider_code=call.runtime.provider_code,
                model=call.runtime.model,
                fallback_reason="provider generation failed",
            )
        result = _deterministic_judgment(call.candidate, call.website_facts)
        result.update(
            ai_fallback_metadata(
                call.runtime.provider_code,
                call.runtime.model,
                "provider generation failed",
            )
        )
        return result


def _target_company_evidence(candidate, website_facts) -> dict:
    return {
        "company_name": candidate.company_name,
        "country": candidate.country,
        "industry": candidate.industry,
        "website": candidate.website,
        "website_title": website_facts.title if website_facts else "",
        "website_text": (website_facts.text_excerpt if website_facts else "")[:2000],
        "matched_terms": list(website_facts.gear_terms) if website_facts else [],
    }


def _deterministic_grounded_judgment(
    candidate,
    website_facts,
    agent_context,
    *,
    provider_code,
    model,
    fallback_reason="real AI disabled",
) -> dict:
    context = agent_context.to_dict()
    mission = context["mission"]
    product = context["product"]
    icps = context["icp_profiles"]
    target_country = str(candidate.country or "").upper()
    geography_fit = target_country in {
        str(item).upper() for item in mission.get("target_countries", [])
    }
    target_industry = _normalized(candidate.industry)
    icp_industries = {
        _normalized(item)
        for icp in icps
        for item in icp.get("target_industries", [])
    }
    industry_fit = any(
        target_industry and (target_industry in item or item in target_industry)
        for item in icp_industries
    )
    evidence_strength = "strong" if website_facts else "limited"
    score = 40 + (20 if geography_fit else 0) + (25 if industry_fit else 0)
    if website_facts:
        score += 10
    score = min(score, 100)
    grade = "A" if score >= 75 else "B" if score >= 50 else "C"
    result = {
        "industry": candidate.industry,
        "uses_gears": bool(website_facts and website_facts.gear_terms),
        "intent": "website" if website_facts else "uncertain",
        "score": score,
        "grade": grade,
        "reason": (
            f"Product fit assessed for {product.get('name_en') or product.get('name_zh')}; "
            f"ICP fit={industry_fit}; geography fit={geography_fit}; purchasing trigger "
            f"is unconfirmed; evidence strength={evidence_strength}; uncertainty retained."
        ),
    }
    result.update(ai_fallback_metadata(provider_code, model, fallback_reason))
    return result


def _normalized(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _deterministic_judgment(candidate, website_facts) -> dict:
    raw = candidate.raw_record if isinstance(candidate.raw_record, dict) else {}
    score, grade, breakdown = grade_candidate(
        primary_type=str(raw.get("primary_type", "")),
        types=tuple(raw.get("types", [])),
        website=candidate.website,
        country=candidate.country,
    )
    gear_terms = tuple(website_facts.gear_terms) if website_facts else ()
    return {
        "industry": candidate.industry or str(raw.get("primary_type", "")),
        "uses_gears": bool(gear_terms) or bool(breakdown.get("gear_terms")),
        "intent": "website" if website_facts else "unknown",
        "score": score,
        "grade": grade,
        "reason": (
            f"确定性判断：行业 {candidate.industry or '未知'}，"
            f"齿轮相关词 {len(gear_terms)} 个，评分 {score}。"
        ),
    }
