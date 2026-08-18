from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Product
from apps.growth.mission_attribution import build_mission_attribution
from apps.growth.mission_planning import approve_mission_plan, generate_mission_plan
from apps.growth.mission_services import create_mission, link_mission_entity
from apps.growth.models import (
    AgentRun,
    AgentRunStep,
    ChannelPackage,
    GrowthMission,
    InboundRfq,
    MissionEntityLink,
    TargetAccount,
)
from apps.growth.work_items import project_work_items
from apps.identity.models import Organization, Role


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="E2E Org", slug="e2e-org")


@pytest.fixture
def manager(db):
    return get_user_model().objects.create_user(username="e2e-manager", password="x")


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


def _mission(organization, manager, product):
    return create_mission(
        organization=organization,
        actor=manager,
        values={
            "title": "E2E mission",
            "objective": "Get replies",
            "target_countries": ["ZA"],
            "target_industries": ["mining"],
            "customer_profile": "",
            "primary_product_id": product.id,
            "start_date": date(2026, 8, 20),
            "end_date": date(2026, 9, 20),
            "allowed_channels": ["EMAIL", "LINKEDIN"],
            "target_account_count": 10,
            "target_reply_count": 2,
            "target_rfq_count": 1,
            "budget_micros": 1000,
        },
    )


def test_mission_plan_work_items_and_attribution_flow(organization, manager, product):
    mission = _mission(organization, manager, product)
    plan = generate_mission_plan(mission=mission, actor=manager)
    approve_mission_plan(mission=mission, plan=plan, actor=manager)
    mission.refresh_from_db()
    assert mission.status == GrowthMission.Status.RUNNING

    account = TargetAccount.objects.create(organization=organization, name="Acme", country="ZA")
    link_mission_entity(
        mission=mission,
        entity=account,
        lane=MissionEntityLink.Lane.ACQUISITION,
        actor=manager,
    )
    InboundRfq.objects.create(
        organization=organization,
        account=account,
        company_name="Acme",
        email="buyer@example.com",
    )

    run = AgentRun.objects.create(
        organization=organization,
        idempotency_key="e2e-run",
        goal="outreach",
        agent_type="proactive",
        status=AgentRun.Status.WAITING_APPROVAL,
    )
    AgentRunStep.objects.create(
        organization=organization,
        run=run,
        index=0,
        tool_name="send_email",
        args={},
        outcome="blocked_approval",
        output={"english_draft": "Hello"},
        approval_token="token",
    )
    link_mission_entity(
        mission=mission,
        entity=run,
        lane=MissionEntityLink.Lane.OUTREACH,
        actor=manager,
    )
    package = ChannelPackage.objects.create(
        organization=organization,
        channel="LINKEDIN",
        payload={"title": "post"},
        status="AWAITING_REVIEW",
        is_demo=False,
    )
    link_mission_entity(
        mission=mission,
        entity=package,
        lane=MissionEntityLink.Lane.SOCIAL,
        actor=manager,
    )

    items = project_work_items(organization=organization, mission=mission)
    assert any(item.kind == "CONFIGURATION_BLOCK" for item in items)
    assert any(item.kind == "SOCIAL_REVIEW" for item in items)

    attribution = build_mission_attribution(mission=mission)
    assert attribution["outcomes"]["confirmed_rfqs"] == 1
    assert attribution["outcomes"]["emails_sent"] is None


def test_role_permissions_are_truthful(db):
    assert "missions.manage" in Role.objects.create_administrator().permissions
    assert "missions.manage" not in Role.objects.create_operator().permissions
    assert "missions.read" in Role.objects.create_operator().permissions
