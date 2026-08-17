import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.agent.acquisition import run_proactive_acquisition
from apps.growth.models import AgentRun, DiscoveryCandidate, FollowUp, OutreachMessage, TargetAccount
from apps.identity.models import Membership, Organization, Role


RUNS_URL = "/api/v1/growth/agent/runs"


def _client(organization, *, reader=False, suffix="manager"):
    role = Role.objects.create_read_only() if reader else Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"agent-api-{suffix}",
        password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Agent API", slug="agent-api")


def _candidate(organization):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="PT Mitra",
        country="Vietnam",
        website="",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
        record_hash="agent-api-hash",
        is_demo=False,
    )


def test_list_detail_and_approve_agent_run(organization):
    candidate = _candidate(organization)
    run_proactive_acquisition(organization=organization, candidate_id=str(candidate.id))
    client = _client(organization)

    listing = client.get(RUNS_URL)
    assert listing.status_code == 200
    assert listing.data[0]["status"] == "WAITING_APPROVAL"
    assert listing.data[0]["pending_approval"]["tool_name"] == "send_email"

    run_id = listing.data[0]["id"]
    detail = client.get(f"{RUNS_URL}/{run_id}")
    assert detail.status_code == 200
    draft_step = next(step for step in detail.data["steps"] if step["tool_name"] == "draft_outreach")
    assert draft_step["output"]["english_draft"]

    approve = client.post(f"{RUNS_URL}/{run_id}/approve", {"decision": "approve"}, format="json")
    assert approve.status_code == 200
    assert approve.data["status"] == "COMPLETED"

    account = TargetAccount.objects.get(
        organization=organization,
        source_identity=f"candidate:{candidate.id}",
    )
    follow_up = FollowUp.objects.get(organization=organization, account=account)
    assert follow_up.stage == "EMAIL_1_SENT"


def test_reader_cannot_approve(organization):
    candidate = _candidate(organization)
    run_proactive_acquisition(organization=organization, candidate_id=str(candidate.id))
    run = AgentRun.objects.get(
        organization=organization,
        idempotency_key=f"proactive:{candidate.id}",
    )
    reader = _client(organization, reader=True, suffix="reader")
    response = reader.post(
        f"{RUNS_URL}/{run.id}/approve",
        {"decision": "approve"},
        format="json",
    )
    assert response.status_code == 403


def test_growth_events_api(organization):
    from apps.growth.growth_events import emit_growth_event

    emit_growth_event(
        organization=organization,
        event_type="email.sent",
        entity_type="account",
        entity_id="a1",
        idempotency_key="event-1",
    )
    client = _client(organization, suffix="events")

    listing = client.get("/api/v1/growth/events?unpublished=true")
    assert listing.status_code == 200
    assert listing.data[0]["event_type"] == "email.sent"

    event_id = listing.data[0]["id"]
    ack = client.post(
        "/api/v1/growth/events/acknowledge",
        {"event_ids": [event_id]},
        format="json",
    )
    assert ack.status_code == 200
    assert ack.data["acknowledged"] == 1
    assert client.get("/api/v1/growth/events?unpublished=true").data == []


def test_rejected_run_does_not_reappear(organization):
    candidate = _candidate(organization)
    run_proactive_acquisition(organization=organization, candidate_id=str(candidate.id))
    run = AgentRun.objects.get(
        organization=organization,
        idempotency_key=f"proactive:{candidate.id}",
    )
    client = _client(organization, suffix="reject")
    response = client.post(
        f"{RUNS_URL}/{run.id}/approve",
        {"decision": "reject"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "REJECTED"

    result = run_proactive_acquisition(organization=organization, candidate_id=str(candidate.id))
    assert result.status == "rejected"
    assert result.pending_approval is None
    account = TargetAccount.objects.get(
        organization=organization,
        source_identity=f"candidate:{candidate.id}",
    )
    assert not OutreachMessage.objects.filter(
        organization=organization,
        account=account,
        status=OutreachMessage.Status.SENT,
    ).exists()
