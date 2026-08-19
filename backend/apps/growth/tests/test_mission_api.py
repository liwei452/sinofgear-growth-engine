from datetime import date

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.growth.models import DiscoveryCandidate, GrowthMission, MissionEntityLink
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


def _approve_plan(administrator_client, mission):
    generated = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/generate-plan", {}, format="json"
    )
    assert generated.status_code == 201
    approved = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/approve-plan",
        {"plan_id": generated.data["id"]},
        format="json",
    )
    assert approved.status_code == 200
    mission.refresh_from_db()
    return mission


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


def test_start_content_strategy_links_mission(administrator_client, mission):
    _approve_plan(administrator_client, mission)
    response = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/start-content-strategy", {}, format="json"
    )
    assert response.status_code == 200
    assert MissionEntityLink.objects.filter(
        mission=mission,
        entity_type=MissionEntityLink.EntityType.AGENT_RUN,
        lane=MissionEntityLink.Lane.SOCIAL,
    ).exists()


def test_start_outreach_links_mission(administrator_client, mission, monkeypatch):
    from apps.growth.agent import acquisition as acq

    _approve_plan(administrator_client, mission)
    monkeypatch.setattr(acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com")
    candidate = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Mining Co",
        country="ZA",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="mission-outreach-hash",
        is_demo=False,
    )
    response = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert response.status_code == 200
    assert MissionEntityLink.objects.filter(
        mission=mission,
        entity_type=MissionEntityLink.EntityType.AGENT_RUN,
        lane=MissionEntityLink.Lane.OUTREACH,
    ).exists()


def test_mission_outreach_summary_returns_draft_and_approval_state(
    administrator_client, mission, monkeypatch
):
    from apps.growth.agent import acquisition as acq

    _approve_plan(administrator_client, mission)
    monkeypatch.setattr(acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com")
    candidate = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Mining Co",
        country="ZA",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="mission-outreach-summary-hash",
        is_demo=False,
    )
    started = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert started.status_code == 200

    response = administrator_client.get(
        f"{MISSIONS_URL}/{mission.id}/outreach-summary",
    )

    assert response.status_code == 200
    assert len(response.data) == 1
    item = response.data[0]
    assert item["company_name"] == "Mining Co"
    assert item["draft"] is not None
    assert item["draft"]["english_draft"]
    assert item["draft"]["status"] == "DRAFT"
    assert item["agent_run"]["status"] == "WAITING_APPROVAL"
    assert item["agent_run"]["pending_tool"] == "send_email"


def test_draft_mission_cannot_start_outreach(administrator_client, mission):
    response = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/start-content-strategy", {}, format="json"
    )
    assert response.status_code == 409


def test_mission_candidates_endpoint_returns_linked_candidates(
    administrator_client, mission
):
    from apps.growth.mission_services import link_mission_entity
    from apps.growth.models import DiscoveryCandidate, MissionEntityLink

    linked = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Linked Mining Co",
        country="ZA",
        website="",
        industry="mining",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={},
        record_hash="mission-candidates-hash",
        is_demo=False,
    )
    DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Unlinked Co",
        country="DE",
        website="",
        industry="machinery",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={},
        record_hash="mission-candidates-unlinked",
        is_demo=False,
    )
    link_mission_entity(
        mission=mission,
        entity=linked,
        lane=MissionEntityLink.Lane.ACQUISITION,
    )

    response = administrator_client.get(f"{MISSIONS_URL}/{mission.id}/candidates")

    assert response.status_code == 200
    assert [candidate["company_name"] for candidate in response.data] == ["Linked Mining Co"]


def test_mission_publish_creates_linked_batch(administrator_client, mission):
    from apps.growth.mission_services import link_mission_entity
    from apps.growth.models import ChannelPackage

    _approve_plan(administrator_client, mission)
    for channel in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"):
        package = ChannelPackage.objects.create(
            organization=mission.organization,
            channel=channel,
            payload={"title": channel},
            status="AWAITING_REVIEW",
            is_demo=True,
        )
        link_mission_entity(
            mission=mission,
            entity=package,
            lane=MissionEntityLink.Lane.SOCIAL,
        )

    response = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/publish",
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["is_demo"] is True
    assert MissionEntityLink.objects.filter(
        mission=mission,
        entity_type=MissionEntityLink.EntityType.PUBLISH_BATCH,
    ).exists()


def test_same_candidate_gets_distinct_agent_runs_per_mission(
    administrator_client, mission, monkeypatch
):
    from apps.growth.agent import acquisition as acq
    from apps.growth.models import AgentRun

    _approve_plan(administrator_client, mission)
    monkeypatch.setattr(
        acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com"
    )
    candidate = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Shared Candidate Co",
        country="ZA",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="mission-distinct-runs",
        is_demo=False,
    )

    first = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert first.status_code == 200

    owner = get_user_model().objects.create_user(
        username="mission-second-owner", password="x"
    )
    second_mission = GrowthMission.objects.create(
        organization=mission.organization,
        title="Second pilot",
        objective="Obtain qualified replies",
        target_countries=["DE"],
        target_industries=["machinery"],
        primary_product=mission.primary_product,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 10, 1),
        allowed_channels=["EMAIL"],
        attribution_code="gm-second-mission",
        created_by=owner,
    )
    _approve_plan(administrator_client, second_mission)

    second = administrator_client.post(
        f"{MISSIONS_URL}/{second_mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert second.status_code == 200

    assert AgentRun.objects.filter(
        organization=mission.organization,
        idempotency_key=f"proactive:{mission.id}:{candidate.id}",
    ).exists()
    assert AgentRun.objects.filter(
        organization=mission.organization,
        idempotency_key=f"proactive:{second_mission.id}:{candidate.id}",
    ).exists()


def test_mission_outreach_approval_resumes_right_run(
    administrator_client, mission, monkeypatch
):
    from apps.growth.agent import acquisition as acq
    from apps.growth.models import AgentRun

    _approve_plan(administrator_client, mission)
    monkeypatch.setattr(
        acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com"
    )
    candidate = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Approve Co",
        country="ZA",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="mission-approve-run",
        is_demo=False,
    )
    started = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert started.status_code == 200
    run_id = started.data["id"]

    approved = administrator_client.post(
        f"/api/v1/growth/agent/runs/{run_id}/approve",
        {"decision": "approve"},
        format="json",
    )

    assert approved.status_code == 200
    assert approved.data["status"] != AgentRun.Status.WAITING_APPROVAL


def test_same_candidate_approval_resumes_each_mission_run(
    administrator_client, mission, monkeypatch
):
    from apps.growth.agent import acquisition as acq
    from apps.growth.models import AgentRun

    _approve_plan(administrator_client, mission)
    monkeypatch.setattr(
        acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com"
    )
    candidate = DiscoveryCandidate.objects.create(
        organization=mission.organization,
        company_name="Dual Mission Co",
        country="ZA",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="mission-dual-approve",
        is_demo=False,
    )
    first = administrator_client.post(
        f"{MISSIONS_URL}/{mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert first.status_code == 200

    owner = get_user_model().objects.create_user(
        username="mission-approve-owner", password="x"
    )
    second_mission = GrowthMission.objects.create(
        organization=mission.organization,
        title="Second approve pilot",
        objective="Obtain qualified replies",
        target_countries=["DE"],
        target_industries=["machinery"],
        primary_product=mission.primary_product,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 10, 1),
        allowed_channels=["EMAIL"],
        attribution_code="gm-second-approve",
        created_by=owner,
    )
    _approve_plan(administrator_client, second_mission)
    second = administrator_client.post(
        f"{MISSIONS_URL}/{second_mission.id}/candidates/{candidate.id}/start-outreach",
        {},
        format="json",
    )
    assert second.status_code == 200
    assert first.data["id"] != second.data["id"]

    first_approved = administrator_client.post(
        f"/api/v1/growth/agent/runs/{first.data['id']}/approve",
        {"decision": "approve"},
        format="json",
    )
    second_approved = administrator_client.post(
        f"/api/v1/growth/agent/runs/{second.data['id']}/approve",
        {"decision": "approve"},
        format="json",
    )

    assert first_approved.status_code == 200
    assert second_approved.status_code == 200
    assert first_approved.data["status"] != AgentRun.Status.WAITING_APPROVAL
    assert second_approved.data["status"] != AgentRun.Status.WAITING_APPROVAL
