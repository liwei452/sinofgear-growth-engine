from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.catalog.models import Product
from apps.growth.models import GrowthMission, MissionEntityLink, TargetAccount
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Mission Org", slug="mission-org")


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="mission-user", password="x")


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
def account(db, organization):
    return TargetAccount.objects.create(organization=organization, name="Acme", country="ZA")


@pytest.fixture
def mission(db, organization, user, product):
    return GrowthMission.objects.create(
        organization=organization,
        title="South Africa mining pilot",
        objective="Generate qualified replies and RFQs",
        target_countries=["ZA"],
        target_industries=["mining equipment"],
        primary_product=product,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 20),
        allowed_channels=["EMAIL", "LINKEDIN"],
        attribution_code="gm-test-mission",
        created_by=user,
    )


def test_growth_mission_requires_a_real_target_and_valid_dates(organization, user):
    mission = GrowthMission(
        organization=organization,
        title="South Africa mining pilot",
        objective="Generate qualified replies and RFQs",
        target_countries=[],
        target_industries=["mining equipment"],
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 19),
        allowed_channels=["EMAIL", "LINKEDIN"],
        created_by=user,
    )
    with pytest.raises(ValidationError):
        mission.full_clean()


def test_mission_link_is_unique_per_entity_inside_one_mission(mission, account, user):
    MissionEntityLink.objects.create(
        organization=mission.organization,
        mission=mission,
        entity_type=MissionEntityLink.EntityType.TARGET_ACCOUNT,
        entity_id=account.id,
        lane=MissionEntityLink.Lane.ACQUISITION,
        linked_by=user,
    )
    with pytest.raises(IntegrityError):
        MissionEntityLink.objects.create(
            organization=mission.organization,
            mission=mission,
            entity_type=MissionEntityLink.EntityType.TARGET_ACCOUNT,
            entity_id=account.id,
            lane=MissionEntityLink.Lane.ACQUISITION,
            linked_by=user,
        )


def test_plan_version_is_unique_per_mission(mission, user):
    from apps.growth.models import MissionPlan

    MissionPlan.objects.create(
        organization=mission.organization,
        mission=mission,
        version=1,
        snapshot={"summary": "plan"},
        generation_mode=MissionPlan.GenerationMode.AUTOMATION,
        created_by=user,
    )
    with pytest.raises(IntegrityError):
        MissionPlan.objects.create(
            organization=mission.organization,
            mission=mission,
            version=1,
            snapshot={"summary": "duplicate"},
            generation_mode=MissionPlan.GenerationMode.AUTOMATION,
            created_by=user,
        )
