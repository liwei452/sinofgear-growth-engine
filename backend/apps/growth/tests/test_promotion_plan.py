import pytest
from django.utils import timezone

from apps.growth.models import MarketCountryProfile
from apps.growth.promotion_plan import generate_promotion_plan
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Promotion plan", slug="promotion-plan")


def test_deterministic_plan_is_built_from_active_market(organization):
    MarketCountryProfile.objects.create(
        organization=organization,
        country_code="VNM",
        country_label="Vietnam",
        status=MarketCountryProfile.Status.ACTIVE_MARKET,
        route="CUSTOMS_STRONG",
        route_label="海关数据驱动",
        recommended_wave="第一波",
        priority_order=1,
        last_researched_at=timezone.now().date(),
        is_demo=False,
        suitable_industries=["Mining equipment", "Agricultural machinery"],
        recommendation_reasons=["齿轮需求明确"],
    )

    plan = generate_promotion_plan(organization)

    assert plan["target_markets"][0]["country_label"] == "Vietnam"
    assert any(audience["industry"] == "Mining equipment" for audience in plan["audiences"])
    assert set(plan["channels"]) == {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"}
    assert plan["period_weeks"] == 8
    assert plan["content_themes"]
