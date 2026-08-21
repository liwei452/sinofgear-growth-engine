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
) -> dict:
    """Resolve tenant AI configuration before leaving the database transaction."""

    from .models import DiscoveryCandidate

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
        result = _deterministic_judgment(call.candidate, call.website_facts)
        result.update(
            ai_fallback_metadata(
                call.runtime.provider_code,
                call.runtime.model,
                "real AI disabled",
            )
        )
        return result

    snapshot = {
        "company_name": call.candidate.company_name,
        "country": call.candidate.country,
        "industry": call.candidate.industry,
        "website": call.candidate.website,
        "website_title": website_facts.title if website_facts else "",
        "website_text": (website_facts.text_excerpt if website_facts else "")[:2000],
        "gear_terms": list(website_facts.gear_terms) if website_facts else [],
    }
    prompt = (
        "Analyze this company for industrial gear and transmission buyer fit.\n||INPUT:"
        + json.dumps(snapshot, ensure_ascii=False)
    )
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
        result = _deterministic_judgment(call.candidate, call.website_facts)
        result.update(
            ai_fallback_metadata(
                call.runtime.provider_code,
                call.runtime.model,
                "provider generation failed",
            )
        )
        return result


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
