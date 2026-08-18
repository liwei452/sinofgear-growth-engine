from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Product
from apps.growth.mission_planning import (
    MissionPlanGenerationError,
    approve_mission_plan,
    generate_mission_plan,
)
from apps.growth.models import GrowthMission, MissionPlan
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Plan Org", slug="plan-org")


@pytest.fixture
def operator(db):
    return get_user_model().objects.create_user(username="operator", password="x")


@pytest.fixture
def product(db, organization):
    return Product.objects.create(
        organization=organization,
        name_en="Helical Gear",
        module_min=1,
        module_max=2,
        tooth_count_min=10,
        tooth_count_max=20,
        pressure_angle=20,
        moq=1,
        status=Product.Status.ACTIVE,
        manufacturing_capabilities=["Hobbing"],
        inspection_capabilities=["CMM"],
    )


@pytest.fixture
def mission(db, organization, operator, product):
    return GrowthMission.objects.create(
        organization=organization,
        title="South Africa mining pilot",
        objective="Obtain qualified replies and RFQs",
        target_countries=["ZA"],
        target_industries=["mining equipment"],
        primary_product=product,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 20),
        allowed_channels=["EMAIL", "LINKEDIN"],
        attribution_code="gm-plan-test",
        created_by=operator,
    )


def test_unconfigured_runtime_creates_truthful_automation_plan(mission, operator):
    plan = generate_mission_plan(mission=mission, actor=operator)
    assert plan.generation_mode == MissionPlan.GenerationMode.AUTOMATION
    assert plan.provider == ""
    assert plan.snapshot["customer_development"]["approval_policy"] == "EVERY_EMAIL"
    assert plan.snapshot["social_growth"]["approval_policy"] == "CONTENT_GROUP"


def test_approved_plan_starts_mission_and_supersedes_old_draft(mission, operator):
    first = generate_mission_plan(mission=mission, actor=operator)
    second = generate_mission_plan(mission=mission, actor=operator)
    approved = approve_mission_plan(mission=mission, plan=second, actor=operator)
    first.refresh_from_db()
    mission.refresh_from_db()
    assert approved.status == MissionPlan.Status.APPROVED
    assert first.status == MissionPlan.Status.SUPERSEDED
    assert mission.status == GrowthMission.Status.RUNNING


def test_ai_plan_with_wrong_attribution_is_rejected(mission, operator, monkeypatch):
    from apps.ai.provider_config import ProductAIRuntime
    from apps.growth import mission_planning

    class Provider:
        last_usage = None

        def generate(self, *, prompt, schema):
            return {
                "summary": "x",
                "customer_development": {
                    "daily_discovery_volume": 20,
                    "qualification_evidence": ["x"],
                    "outreach_angle": "x",
                    "approval_policy": "EVERY_EMAIL",
                    "stop_conditions": ["REPLIED", "UNSUBSCRIBED", "HARD_BOUNCE"],
                },
                "social_growth": {
                    "channels": ["LINKEDIN"],
                    "weekly_cadence": 3,
                    "content_themes": ["x"],
                    "approval_policy": "CONTENT_GROUP",
                },
                "attribution": {
                    "attribution_code": "gm-wrong",
                    "utm_campaign": "x",
                    "confidence_labels": ["CONFIRMED", "ASSISTED", "UNATTRIBUTED"],
                },
                "risks": ["x"],
            }

    monkeypatch.setattr(
        mission_planning,
        "resolve_product_ai",
        lambda org: ProductAIRuntime(
            mode="CONFIGURED_AI",
            provider_label="DeepSeek",
            provider_code="deepseek",
            model="deepseek-chat",
            configured=True,
            real_requests_enabled=True,
            provider=Provider(),
        ),
    )

    with pytest.raises(MissionPlanGenerationError):
        generate_mission_plan(mission=mission, actor=operator)
