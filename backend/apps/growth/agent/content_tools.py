"""Agent tools that connect the growth engine to the content system."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count

from apps.campaigns.models import Campaign
from apps.campaigns.services import create_campaign, create_content_brief
from apps.identity.models import Membership

from .persistent import continue_agent_run
from .planner import DeterministicPlanner, Plan
from .tools import Tool, ToolRegistry, ToolResult
from ..models import AgentRun, DiscoveryCandidate, InboundRfq


def content_opportunity_signals(organization) -> dict[str, Any]:
    candidates = DiscoveryCandidate.objects.filter(
        organization=organization,
        status=DiscoveryCandidate.Status.ACCEPTED,
    )
    top_industries = list(
        candidates.values("industry")
        .annotate(count=Count("id"))
        .order_by("-count", "industry")[:5]
    )
    recent_rfqs = list(
        InboundRfq.objects.filter(organization=organization)
        .order_by("-created_at", "-id")[:20]
    )
    need_slugs = [rfq.need_slug for rfq in recent_rfqs if rfq.need_slug]
    high_intent_count = candidates.filter(intent_score__gte=40).count()
    return {
        "accepted_candidate_count": candidates.count(),
        "high_intent_candidate_count": high_intent_count,
        "top_industries": top_industries,
        "recent_need_slugs": need_slugs[:10],
        "recent_rfq_count": len(recent_rfqs),
    }


def propose_content_opportunities(signals: dict[str, Any]) -> list[dict[str, Any]]:
    industries = signals.get("top_industries") or []
    needs = signals.get("recent_need_slugs") or []
    industry = industries[0]["industry"] if industries else "industrial machinery"
    need = needs[0] if needs else "gear and transmission selection"
    return [
        {
            "topic": f"How to Select Gear Material for {industry.title()}",
            "reasons": [
                f"{signals.get('accepted_candidate_count', 0)} accepted candidates in scope",
                f"{signals.get('high_intent_candidate_count', 0)} high-intent website visitors",
                f"recent RFQs mention {need}",
            ],
            "platforms": ["LinkedIn", "Website"],
            "target": "Build engineering capability trust and invite drawings",
        }
    ]


def _analyze_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        signals = content_opportunity_signals(organization)
        proposals = propose_content_opportunities(signals)
        return ToolResult(ok=True, output={"signals": signals, "proposals": proposals})

    return Tool(
        name="analyze_content_opportunities",
        description="Analyze growth signals and propose content topics with evidence.",
        parameters={"type": "object", "properties": {}},
        risk="read",
        func=func,
    )


def _get_or_create_campaign(organization, name: str) -> Campaign:
    campaign = Campaign.objects.filter(organization=organization, name=name).order_by("id").first()
    if campaign is not None:
        return campaign
    return create_campaign(
        organization=organization,
        values={"name": name, "description": "Agent-generated content strategy campaign"},
        product_ids=(),
    )


def _create_brief_tool(organization, creator_id: str) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        creator = get_user_model().objects.filter(id=creator_id).first()
        if creator is None:
            return ToolResult(ok=False, error="creator not found.")
        if not Membership.objects.filter(user=creator, organization=organization).exists():
            return ToolResult(ok=False, error="creator is not a member of this organization.")

        signals = content_opportunity_signals(organization)
        proposals = propose_content_opportunities(signals)
        proposal = proposals[0] if proposals else {"topic": "Gear selection", "reasons": []}
        top_industry = (signals.get("top_industries") or [{}])[0].get("industry", "")
        campaign = _get_or_create_campaign(organization, "Content Strategy")
        brief = create_content_brief(
            organization=organization,
            campaign=campaign,
            creator=creator,
            values={
                "target_country": args.get("target_country", ""),
                "customer_type": args.get("customer_type", top_industry),
                "content_objective": f"{proposal['topic']}. " + " ".join(proposal["reasons"]),
                "cta": args.get("cta", "Upload drawings"),
                "landing_page_url": args.get("landing_page_url", ""),
                "language": args.get("language", "en"),
                "prohibited_claims": args.get("prohibited_claims", []),
                "selling_points": args.get("selling_points", []),
                "advantages": args.get("advantages", []),
                "keywords": args.get("keywords", signals.get("recent_need_slugs", [])),
            },
            product_ids=(),
            asset_ids=(),
            platform_ids=(),
            concept_links=(),
        )
        return ToolResult(
            ok=True,
            output={
                "brief_id": str(brief.id),
                "campaign_id": str(campaign.id),
                "topic": proposal["topic"],
                "status": brief.status,
            },
        )

    return Tool(
        name="create_content_brief",
        description="Create a content brief from the analyzed content opportunity.",
        parameters={"type": "object", "properties": {}},
        risk="write",
        func=func,
    )


def build_content_strategy_tools(organization, creator_id: str | None = None) -> list[Tool]:
    tools = [_analyze_tool(organization)]
    if creator_id:
        tools.append(_create_brief_tool(organization, creator_id))
    return tools


def run_content_strategy_agent(
    *, organization, creator_id: str | None = None, approvals=None,
) -> Any:
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=f"content-strategy:{organization.id}",
        defaults={
            "goal": "content strategy",
            "agent_type": "content_strategy",
            "resume_args": {"creator_id": creator_id},
            "max_steps": 5,
        },
    )
    tools = ToolRegistry(build_content_strategy_tools(organization, creator_id=creator_id))
    actions = [
        Plan(
            reasoning="analyze content opportunities",
            tool_name="analyze_content_opportunities",
            tool_args={},
        )
    ]
    if creator_id:
        actions.append(
            Plan(reasoning="create content brief", tool_name="create_content_brief", tool_args={})
        )
    planner = DeterministicPlanner(actions)
    return continue_agent_run(run=run, planner=planner, tools=tools, approvals=approvals)
