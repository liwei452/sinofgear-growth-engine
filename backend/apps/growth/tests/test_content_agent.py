import pytest

from apps.growth.agent.content_tools import run_content_strategy_agent
from apps.growth.models import DiscoveryCandidate, InboundRfq
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Content", slug="content")


def test_content_strategy_agent_proposes_opportunities(organization):
    DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Mining Co",
        country="ZAF",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="content-hash",
        is_demo=False,
        intent_score=50,
    )
    InboundRfq.objects.create(
        organization=organization,
        company_name="Mining Co",
        email="p@x.com",
        need_slug="gearbox",
        message="Need gearbox",
    )

    result = run_content_strategy_agent(organization=organization)

    assert result.status == "completed"
    output = result.steps[-1].output
    assert output["signals"]["accepted_candidate_count"] == 1
    assert output["signals"]["high_intent_candidate_count"] == 1
    assert output["proposals"]
    assert "Mining Equipment" in output["proposals"][0]["topic"]
    assert "gearbox" in output["proposals"][0]["reasons"][-1]


def test_content_strategy_agent_creates_brief(organization):
    from django.contrib.auth import get_user_model

    from apps.campaigns.models import ContentBrief
    from apps.identity.models import Membership, Role

    DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Mining Co",
        country="ZAF",
        website="",
        industry="mining equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "mining"},
        record_hash="content-brief-hash",
        is_demo=False,
        intent_score=50,
    )
    InboundRfq.objects.create(
        organization=organization,
        company_name="Mining Co",
        email="p@x.com",
        need_slug="gearbox",
        message="Need gearbox",
    )
    user = get_user_model().objects.create_user(username="creator", password="pw")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_operator(),
    )

    first = run_content_strategy_agent(organization=organization, creator_id=str(user.id))
    assert first.status == "waiting_approval"
    token = first.pending_approval.approval_token

    result = run_content_strategy_agent(
        organization=organization,
        creator_id=str(user.id),
        approvals={token},
    )
    assert result.status == "completed"
    brief_step = next(
        step
        for step in result.steps
        if step.tool_name == "create_content_brief" and step.outcome == "succeeded"
    )
    assert brief_step.output["brief_id"]
    assert brief_step.output["topic"]
    assert ContentBrief.objects.filter(id=brief_step.output["brief_id"]).exists()
