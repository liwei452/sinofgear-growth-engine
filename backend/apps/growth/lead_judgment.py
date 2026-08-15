import json

from django.conf import settings

from integrations.ai.providers import provider_registry

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
    provider_code = getattr(settings, "PRODUCT_AI_PROVIDER", "fake")
    if provider_code not in {"deepseek"}:
        return _deterministic_judgment(candidate, website_facts)

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
        return provider_registry.get(provider_code).generate(
            prompt=prompt,
            schema=LEAD_JUDGMENT_SCHEMA,
        )
    except Exception:
        return _deterministic_judgment(candidate, website_facts)


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
