import pytest

from apps.ai.models import OrganizationAIProviderConfig
from apps.growth.agent.execution import PlannerConfigurationUnavailable
from apps.growth.agent.content_tools import run_content_strategy_agent
from apps.growth.models import AgentRun, DiscoveryCandidate, InboundRfq
from apps.identity.models import Membership, Organization, Role
from integrations.secrets import encrypt_secret


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


def test_content_strategy_agent_key_is_scoped_to_calendar_day(organization, monkeypatch):
    from datetime import timezone as dt_timezone

    from django.utils import timezone as real_timezone

    from apps.growth.agent import content_tools
    from apps.growth.models import AgentRun

    class Clock:
        def __init__(self, day):
            self.day = day

        def now(self):
            return real_timezone.datetime(2026, 8, self.day, 0, 0, tzinfo=dt_timezone.utc)

    clock = Clock(18)
    monkeypatch.setattr(content_tools, "timezone", clock)

    run_content_strategy_agent(organization=organization)
    run_content_strategy_agent(organization=organization)
    assert AgentRun.objects.filter(
        organization=organization, agent_type="content_strategy"
    ).count() == 1

    clock.day = 19
    run_content_strategy_agent(organization=organization)
    assert AgentRun.objects.filter(
        organization=organization, agent_type="content_strategy"
    ).count() == 2


def test_configured_content_strategy_persists_truthful_ai_execution(organization, monkeypatch):
    OrganizationAIProviderConfig.objects.create(
        organization=organization,
        provider="deepseek",
        model="deepseek-chat",
        encrypted_api_key=encrypt_secret("organization-planner-key"),
        enabled=True,
    )

    def generate(_provider, *, prompt, schema):
        assert "Choose the next bounded action" in prompt
        return {
            "reasoning": "inspect evidence before choosing a topic",
            "tool_name": "analyze_content_opportunities",
            "tool_args": {},
            "terminal_reason": None,
        } if '"step_index": 0' in prompt else {
            "reasoning": "analysis is complete",
            "tool_name": None,
            "tool_args": None,
            "terminal_reason": "complete",
        }

    monkeypatch.setattr("integrations.ai.providers.DeepSeekAIProvider.generate", generate)

    result = run_content_strategy_agent(organization=organization)

    assert result.status == "completed"
    run = AgentRun.objects.get(organization=organization, agent_type="content_strategy")
    assert run.execution_mode == "AI_AGENT"
    assert run.planner_provider == "deepseek"
    assert run.planner_model == "deepseek-chat"


def test_ai_agent_resume_refuses_a_silent_model_switch(organization, monkeypatch, django_user_model):
    config = OrganizationAIProviderConfig.objects.create(
        organization=organization,
        provider="deepseek",
        model="deepseek-chat",
        encrypted_api_key=encrypt_secret("organization-planner-key"),
        enabled=True,
    )
    user = django_user_model.objects.create_user(username="ai-planner-reviewer")
    Membership.objects.create(user=user, organization=organization, role=Role.objects.create_operator())

    def generate(_provider, *, prompt, schema):
        if '"step_index": 0' in prompt:
            return {"reasoning": "analyze", "tool_name": "analyze_content_opportunities", "tool_args": {}, "terminal_reason": None}
        return {"reasoning": "draft", "tool_name": "create_content_brief", "tool_args": {}, "terminal_reason": None}

    monkeypatch.setattr("integrations.ai.providers.DeepSeekAIProvider.generate", generate)
    first = run_content_strategy_agent(organization=organization, creator_id=str(user.id))
    assert first.status == "waiting_approval"

    config.model = "deepseek-reasoner"
    config.save(update_fields=["model", "updated_at"])

    with pytest.raises(PlannerConfigurationUnavailable, match="planner configuration"):
        run_content_strategy_agent(
            organization=organization,
            creator_id=str(user.id),
            approvals={first.pending_approval.approval_token},
        )


def _mission_with_channels(organization, creator, channels):
    from datetime import date

    from apps.catalog.models import Product
    from apps.growth.models import GrowthMission

    product = Product.objects.create(
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
    return GrowthMission.objects.create(
        organization=organization,
        title="Platform mission",
        objective="Leads",
        target_countries=["DE"],
        target_industries=["machinery"],
        primary_product=product,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 1),
        allowed_channels=channels,
        attribution_code=f"gm-{channels[0].lower()}",
        created_by=creator,
    )


def test_content_strategy_agent_selects_mission_platforms(organization, django_user_model):
    from apps.campaigns.models import ContentBrief
    from apps.platforms.models import Platform

    user = django_user_model.objects.create_user(username="platform-creator")
    Membership.objects.create(
        user=user, organization=organization, role=Role.objects.create_operator()
    )
    Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    Platform.objects.create(code="FACEBOOK", name="Facebook")
    mission = _mission_with_channels(
        organization, user, ["LINKEDIN", "FACEBOOK"]
    )

    first = run_content_strategy_agent(
        organization=organization, creator_id=str(user.id), mission_id=str(mission.id)
    )
    assert first.status == "waiting_approval"
    result = run_content_strategy_agent(
        organization=organization,
        creator_id=str(user.id),
        mission_id=str(mission.id),
        approvals={first.pending_approval.approval_token},
    )

    assert result.status == "completed"
    brief_step = next(
        step
        for step in result.steps
        if step.tool_name == "create_content_brief" and step.outcome == "succeeded"
    )
    brief = ContentBrief.objects.get(id=brief_step.output["brief_id"])
    assert set(brief.platform_links.values_list("platform__code", flat=True)) == {
        "LINKEDIN",
        "FACEBOOK",
    }


def test_content_strategy_agent_rejects_missing_platform_definition(
    organization, django_user_model
):
    from apps.platforms.models import Platform

    user = django_user_model.objects.create_user(username="missing-platform-creator")
    Membership.objects.create(
        user=user, organization=organization, role=Role.objects.create_operator()
    )
    Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    mission = _mission_with_channels(
        organization, user, ["LINKEDIN", "MISSING_CHANNEL"]
    )

    first = run_content_strategy_agent(
        organization=organization, creator_id=str(user.id), mission_id=str(mission.id)
    )
    assert first.status == "waiting_approval"
    result = run_content_strategy_agent(
        organization=organization,
        creator_id=str(user.id),
        mission_id=str(mission.id),
        approvals={first.pending_approval.approval_token},
    )

    assert result.status == "failed"
    assert "missing platform definitions" in result.terminal_reason
