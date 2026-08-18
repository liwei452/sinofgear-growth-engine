from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.catalog.models import Product
from apps.growth.mission_attribution import build_mission_attribution
from apps.growth.models import (
    GrowthMission,
    InboundRfq,
    MetricReceipt,
    MissionEntityLink,
    OutreachMessage,
    SalesDeal,
    TargetAccount,
)
from apps.growth.mission_services import link_mission_entity
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Attribution Org", slug="attribution-org")


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="attr-user", password="x")


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
def mission(db, organization, user, product):
    return GrowthMission.objects.create(
        organization=organization,
        title="Attribution mission",
        objective="Get replies",
        target_countries=["ZA"],
        target_industries=["mining"],
        primary_product=product,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 20),
        allowed_channels=["EMAIL"],
        attribution_code="gm-attribution",
        created_by=user,
    )


@pytest.fixture
def mission_data(db, organization, mission, user):
    account = TargetAccount.objects.create(organization=organization, name="Acme", country="ZA")
    link_mission_entity(
        mission=mission,
        entity=account,
        lane=MissionEntityLink.Lane.ACQUISITION,
        actor=user,
    )
    message = OutreachMessage.objects.create(
        organization=organization,
        account=account,
        status=OutreachMessage.Status.REPLIED,
        provider="smtp",
    )
    link_mission_entity(
        mission=mission,
        entity=message,
        lane=MissionEntityLink.Lane.OUTREACH,
        actor=user,
    )
    rfq = InboundRfq.objects.create(
        organization=organization,
        account=account,
        company_name="Acme",
        email="buyer@example.com",
    )
    link_mission_entity(
        mission=mission,
        entity=rfq,
        lane=MissionEntityLink.Lane.ATTRIBUTION,
        actor=user,
    )
    deal = SalesDeal.objects.create(
        organization=organization,
        account=account,
        stage=SalesDeal.Stage.WON,
        quote_amount=Decimal("12500.00"),
    )
    link_mission_entity(
        mission=mission,
        entity=deal,
        lane=MissionEntityLink.Lane.ATTRIBUTION,
        actor=user,
    )
    receipt = MetricReceipt.objects.create(
        organization=organization,
        channel="LINKEDIN",
        payload={"impressions": 900},
        is_demo=False,
    )
    link_mission_entity(
        mission=mission,
        entity=receipt,
        lane=MissionEntityLink.Lane.ATTRIBUTION,
        actor=user,
    )
    return SimpleNamespace(mission=mission)


def test_confirmed_reply_rfq_and_won_deal_are_not_mixed_with_social_impressions(
    mission_data,
):
    result = build_mission_attribution(mission=mission_data.mission)
    assert result["outcomes"]["confirmed_replies"] == 1
    assert result["outcomes"]["confirmed_rfqs"] == 1
    assert result["outcomes"]["won_revenue"]["amount"] == "12500.00"
    assert result["diagnostics"]["impressions"] == 900
    assert result["traces"][0]["confidence"] == "CONFIRMED"


def test_unconnected_email_reports_unavailable_not_zero(mission):
    result = build_mission_attribution(mission=mission)
    assert result["outcomes"]["emails_sent"] is None
    assert result["availability"]["email"] == "NOT_CONNECTED"
