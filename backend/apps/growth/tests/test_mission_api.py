from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.growth.models import GrowthMission
from apps.identity.models import Membership, Organization, Role


MISSIONS_URL = "/api/v1/growth/missions"


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Mission API", slug="mission-api")


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


def _client(organization, role, suffix):
    user = get_user_model().objects.create_user(
        username=f"mission-{suffix}", password="password"
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def administrator_client(db, organization):
    return _client(organization, Role.objects.create_administrator(), "admin")


@pytest.fixture
def operator_client(db, organization):
    return _client(organization, Role.objects.create_operator(), "operator")


@pytest.fixture
def read_only_client(db, organization):
    return _client(organization, Role.objects.create_read_only(), "readonly")


@pytest.fixture
def mission(db, organization, product):
    owner = get_user_model().objects.create_user(username="mission-owner", password="x")
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
        attribution_code="gm-mission-api",
        created_by=owner,
    )


def _payload(product):
    return {
        "title": "South Africa mining pilot",
        "objective": "Obtain qualified replies and RFQs",
        "target_countries": ["ZA"],
        "target_industries": ["mining equipment"],
        "customer_profile": "OEM and maintenance companies",
        "primary_product_id": str(product.id),
        "start_date": "2026-08-20",
        "end_date": "2026-09-20",
        "target_account_count": 100,
        "target_reply_count": 20,
        "target_rfq_count": 5,
        "budget_micros": 100000000,
        "allowed_channels": ["EMAIL", "LINKEDIN", "FACEBOOK"],
    }


def test_manager_creates_and_lists_growth_mission(administrator_client, product):
    response = administrator_client.post(MISSIONS_URL, _payload(product), format="json")
    assert response.status_code == 201
    assert response.data["status"] == "DRAFT"
    listing = administrator_client.get(MISSIONS_URL)
    assert listing.status_code == 200
    assert listing.data[0]["id"] == response.data["id"]


def test_read_only_user_cannot_create_but_can_read(read_only_client, mission):
    assert read_only_client.post(MISSIONS_URL, {}, format="json").status_code == 403
    assert read_only_client.get(f"{MISSIONS_URL}/{mission.id}").status_code == 200


def test_operator_reads_missions_but_cannot_define_strategy(operator_client, mission):
    assert operator_client.get(f"{MISSIONS_URL}/{mission.id}").status_code == 200
    assert operator_client.post(MISSIONS_URL, {}, format="json").status_code == 403


def test_cross_organization_mission_returns_404(administrator_client, organization):
    other_org = Organization.objects.create(name="Other", slug="other")
    other_product = Product.objects.create(
        organization=other_org,
        name_en="Other Gear",
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
    other_owner = get_user_model().objects.create_user(username="other-owner", password="x")
    other_mission = GrowthMission.objects.create(
        organization=other_org,
        title="Other mission",
        objective="Other",
        target_countries=["DE"],
        target_industries=["machinery"],
        primary_product=other_product,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 20),
        allowed_channels=["EMAIL"],
        attribution_code="gm-other",
        created_by=other_owner,
    )
    assert (
        administrator_client.get(f"{MISSIONS_URL}/{other_mission.id}").status_code == 404
    )


def test_invalid_dates_are_rejected(administrator_client, product):
    payload = _payload(product)
    payload["end_date"] = "2026-08-19"
    response = administrator_client.post(MISSIONS_URL, payload, format="json")
    assert response.status_code == 400


def test_generate_and_approve_plan(administrator_client, mission):
    generated = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/generate-plan", {}, format="json"
    )
    assert generated.status_code == 201
    plan_id = generated.data["id"]
    approved = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/approve-plan",
        {"plan_id": plan_id},
        format="json",
    )
    assert approved.status_code == 200
    assert approved.data["status"] == "APPROVED"
    mission.refresh_from_db()
    assert mission.status == GrowthMission.Status.RUNNING


def test_pause_and_resume_mission(administrator_client, mission):
    administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/generate-plan", {}, format="json"
    )
    approved = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/approve-plan",
        {"plan_id": administrator_client.get(f"{MISSIONS_URL}/{mission.id}").data["latest_plan"]["id"]},
        format="json",
    )
    assert approved.status_code == 200
    paused = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/status", {"status": "PAUSED"}, format="json"
    )
    assert paused.status_code == 200
    assert paused.data["status"] == "PAUSED"
    resumed = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/status", {"status": "RUNNING"}, format="json"
    )
    assert resumed.status_code == 200
    assert resumed.data["status"] == "RUNNING"
