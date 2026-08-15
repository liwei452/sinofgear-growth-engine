import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from integrations.ai.providers import provider_registry

from .models import MarketCountryProfile, PromotionPlanApproval


PUBLISH_CHANNELS = ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK")

PROMOTION_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "target_markets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "country_code": {"type": "string"},
                    "country_label": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["country_code", "country_label", "reason"],
            },
        },
        "audiences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "industry": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["industry", "reason"],
            },
        },
        "period_weeks": {"type": "integer", "minimum": 1, "maximum": 52},
        "content_themes": {"type": "array", "items": {"type": "string"}},
        "channels": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": [
        "target_markets", "audiences", "period_weeks",
        "content_themes", "channels", "summary",
    ],
}


def generate_promotion_plan(organization) -> dict:
    provider_code = getattr(settings, "PRODUCT_AI_PROVIDER", "fake")
    if provider_code != "deepseek":
        return _deterministic_plan(organization)
    snapshot = _plan_input(organization)
    prompt = (
        "Create an industrial B2B promotion plan from the verified facts and market profiles.\n"
        "||INPUT:" + json.dumps(snapshot, ensure_ascii=False)
    )
    try:
        return provider_registry.get(provider_code).generate(
            prompt=prompt,
            schema=PROMOTION_PLAN_SCHEMA,
        )
    except Exception:
        return _deterministic_plan(organization)


def _plan_input(organization) -> dict:
    markets = list(_active_markets(organization))
    facts = list(_verified_facts(organization))
    return {
        "markets": [
            {
                "country_code": market.country_code,
                "country_label": market.country_label,
                "industries": market.suitable_industries or [],
                "route": market.route_label,
                "reasons": market.recommendation_reasons or [],
            }
            for market in markets
        ],
        "facts": [
            {"field": fact.field_name, "value": fact.value, "category": fact.category}
            for fact in facts[:50]
        ],
    }


def _deterministic_plan(organization) -> dict:
    markets = list(_active_markets(organization))
    if not markets:
        markets = list(
            MarketCountryProfile.objects.filter(organization=organization, is_demo=False)
            .order_by("priority_order", "country_code")[:3]
        )
    target_markets = [
        {
            "country_code": market.country_code,
            "country_label": market.country_label,
            "reason": (market.recommendation_reasons or ["进入该市场试点"])[0],
        }
        for market in markets
    ]
    industries = list(dict.fromkeys(
        industry for market in markets for industry in (market.suitable_industries or [])
    ))
    audiences = [
        {"industry": industry, "reason": "市场档案中的目标行业"}
        for industry in industries[:5]
    ]
    facts = list(_verified_facts(organization))[:30]
    themes = [f"{fact.field_name}：{fact.value}" for fact in facts[:5]]
    if not themes:
        themes = ["基于已验证产品事实生成内容"]
    return {
        "target_markets": target_markets,
        "audiences": audiences,
        "period_weeks": 8,
        "content_themes": themes,
        "channels": list(PUBLISH_CHANNELS),
        "summary": "由已验证产品事实与市场档案生成，等待人工审核。",
    }


def _active_markets(organization):
    return MarketCountryProfile.objects.filter(
        organization=organization,
        is_demo=False,
        status=MarketCountryProfile.Status.ACTIVE_MARKET,
    ).order_by("priority_order", "country_code")


def _verified_facts(organization):
    from apps.assets.models import ProductEvidenceFact

    return ProductEvidenceFact.objects.filter(
        organization=organization,
        review_status=ProductEvidenceFact.ReviewStatus.VERIFIED,
    ).order_by("created_at")


@transaction.atomic
def approve_promotion_plan(*, organization, actor) -> PromotionPlanApproval:
    plan = generate_promotion_plan(organization)
    approval, _ = PromotionPlanApproval.objects.get_or_create(organization=organization)
    approval.approved_at = timezone.now()
    approval.approved_by = actor
    approval.plan_snapshot = plan
    approval.version += 1
    approval.save(update_fields=[
        "approved_at", "approved_by", "plan_snapshot", "version", "updated_at",
    ])
    return approval


@transaction.atomic
def clear_promotion_plan_approval(*, organization) -> None:
    PromotionPlanApproval.objects.filter(organization=organization).update(
        approved_at=None,
        approved_by=None,
    )


def promotion_plan_status(organization) -> dict:
    approval = PromotionPlanApproval.objects.filter(organization=organization).first()
    return {
        "approved": bool(approval and approval.approved_at),
        "approved_at": approval.approved_at if approval else None,
        "version": approval.version if approval else 0,
    }
