import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Role
from apps.growth.models import MarketCountryProfile
from apps.growth.promotion_plan import (
    approve_promotion_plan,
    clear_promotion_plan_approval,
    generate_promotion_plan,
    promotion_plan_status,
)
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


def test_plan_approval_persists_and_can_be_cleared(organization):
    user = get_user_model().objects.create_user(username="plan-approver", password="pw")
    assert promotion_plan_status(organization)["approved"] is False

    approval = approve_promotion_plan(organization=organization, actor=user)

    assert promotion_plan_status(organization)["approved"] is True
    assert approval.plan_snapshot
    assert approval.version == 1

    clear_promotion_plan_approval(organization=organization)
    assert promotion_plan_status(organization)["approved"] is False


def test_publish_endpoint_requires_approved_plan(organization):
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(username="publish-gate", password="pw")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="pw")

    response = client.post("/api/v1/growth/publish-batches", {}, format="json")

    assert response.status_code == 409
    assert response.data["code"] == "PROMOTION_PLAN_NOT_APPROVED"
