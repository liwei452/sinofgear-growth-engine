"""Agent tools that connect the growth engine to the content system."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from apps.campaigns.models import Campaign
from apps.campaigns.services import create_campaign, create_content_brief
from apps.identity.models import Membership
from apps.knowledge.agent_context import (
    AgentContextPurpose,
    KnowledgeContextError,
    load_agent_context,
    load_or_build_agent_context,
)
from apps.knowledge.models import KnowledgeContextSnapshot
from apps.platforms.models import Platform

from .persistent import continue_agent_run
from .execution import resolve_agent_execution, resolve_run_execution
from .planner import DeterministicPlanner, Plan
from .tools import Tool, ToolRegistry, ToolResult
from ..models import AgentRun, DiscoveryCandidate, GrowthMission, InboundRfq, MissionEntityLink


def _mission_entity_ids(mission_id, entity_type):
    if not mission_id:
        return None
    return set(
        MissionEntityLink.objects.filter(
            mission_id=mission_id,
            entity_type=entity_type,
        ).values_list("entity_id", flat=True)
    )


def _mission_context(agent_context):
    if agent_context is None:
        return {}
    context = agent_context.to_dict()
    mission = context["mission"]
    product = context["product"]
    icp = context["icp_profiles"][0]
    seller = context["seller"]
    page = context["website_pages"][0]
    primary_cta = page.get("primary_cta") or {}

    def claim_text(claim):
        value = claim.get("value")
        if isinstance(value, dict) and value.get("text"):
            return str(value["text"]).strip()
        return str(value).strip()

    selling_points = [
        text for text in (claim_text(claim) for claim in seller["public_claims"]) if text
    ]
    advantages = [
        str(item).strip()
        for item in (
            list(product.get("manufacturing_capabilities") or [])
            + list(product.get("inspection_capabilities") or [])
        )
        if str(item).strip()
    ]
    keywords = list(page.get("seo_keywords") or []) + list(
        mission.get("target_industries") or []
    )
    return {
        "target_country": (mission.get("target_countries") or [""])[0],
        "customer_type": (icp.get("company_types") or [icp.get("name", "")])[0],
        "content_objective": mission.get("objective", ""),
        "language": (icp.get("languages") or [seller["company_profile"].get("default_language", "")])[0],
        "cta": primary_cta.get("label") or "",
        "landing_page_url": primary_cta.get("url") or page.get("canonical_url", ""),
        "prohibited_claims": list(seller.get("prohibited_claims") or []),
        "selling_points": selling_points,
        "advantages": advantages,
        "keywords": list(dict.fromkeys(str(item) for item in keywords if str(item).strip())),
        "product_ids": [str(product["id"])],
        "channels": [c for c in (mission.get("allowed_channels") or []) if c != "EMAIL"],
        "industries": mission.get("target_industries") or [],
        "attribution_code": mission.get("attribution_code", ""),
    }


def content_opportunity_signals(organization, mission_id: str | None = None) -> dict[str, Any]:
    candidates = DiscoveryCandidate.objects.filter(
        organization=organization,
        status=DiscoveryCandidate.Status.ACCEPTED,
    )
    rfqs = InboundRfq.objects.filter(organization=organization)
    candidate_ids = _mission_entity_ids(mission_id, MissionEntityLink.EntityType.DISCOVERY_CANDIDATE)
    rfq_ids = _mission_entity_ids(mission_id, MissionEntityLink.EntityType.INBOUND_RFQ)
    if candidate_ids is not None:
        candidates = candidates.filter(id__in=candidate_ids)
    if rfq_ids is not None:
        rfqs = rfqs.filter(id__in=rfq_ids)
    top_industries = list(
        candidates.values("industry")
        .annotate(count=Count("id"))
        .order_by("-count", "industry")[:5]
    )
    recent_rfqs = list(
        rfqs.order_by("-created_at", "-id")[:20]
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


def _analyze_tool(organization, mission_id: str | None = None) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        signals = content_opportunity_signals(organization, mission_id=mission_id)
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


def _create_brief_tool(
    organization,
    creator_id: str,
    mission_id: str | None = None,
    agent_context=None,
) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        creator = get_user_model().objects.filter(id=creator_id).first()
        if creator is None:
            return ToolResult(ok=False, error="creator not found.")
        if not Membership.objects.filter(user=creator, organization=organization).exists():
            return ToolResult(ok=False, error="creator is not a member of this organization.")

        mission_context = _mission_context(agent_context)
        platform_codes = [
            code for code in mission_context.get("channels", []) if code
        ]
        if mission_id and not platform_codes:
            return ToolResult(
                ok=False,
                error="Mission has no social content channels.",
            )
        platforms = list(
            Platform.objects.filter(code__in=platform_codes).order_by("code")
        )
        resolved_codes = {platform.code for platform in platforms}
        missing = [code for code in platform_codes if code not in resolved_codes]
        if missing:
            return ToolResult(
                ok=False,
                error=(
                    "Mission channels are missing platform definitions: "
                    + ", ".join(missing)
                ),
            )
        platform_ids = tuple(platform.id for platform in platforms)
        signals = content_opportunity_signals(organization, mission_id=mission_id)
        proposals = propose_content_opportunities(signals)
        proposal = proposals[0] if proposals else {"topic": "Gear selection", "reasons": []}
        top_industry = (signals.get("top_industries") or [{}])[0].get("industry", "")
        keywords = list(signals.get("recent_need_slugs", []))
        keywords.extend(mission_context.get("industries", []))
        campaign = _get_or_create_campaign(
            organization,
            f"Content Strategy: {mission_id}" if mission_id else "Content Strategy",
        )
        if mission_id:
            values = {
                key: mission_context[key]
                for key in (
                    "target_country",
                    "customer_type",
                    "content_objective",
                    "cta",
                    "landing_page_url",
                    "language",
                    "prohibited_claims",
                    "selling_points",
                    "advantages",
                    "keywords",
                )
            }
            snapshot = KnowledgeContextSnapshot.objects.get(
                pk=agent_context.snapshot_id,
                organization=organization,
            )
        else:
            values = {
                "target_country": args.get("target_country", ""),
                "customer_type": args.get("customer_type", top_industry),
                "content_objective": f"{proposal['topic']}. " + " ".join(proposal["reasons"]),
                "cta": args.get("cta", "Upload drawings"),
                "landing_page_url": args.get("landing_page_url", ""),
                "language": args.get("language", "en"),
                "prohibited_claims": args.get("prohibited_claims", []),
                "selling_points": args.get("selling_points", []),
                "advantages": args.get("advantages", []),
                "keywords": args.get("keywords", keywords),
            }
            snapshot = None
        brief = create_content_brief(
            organization=organization,
            campaign=campaign,
            creator=creator,
            values=values,
            product_ids=tuple(mission_context.get("product_ids", ())),
            asset_ids=(),
            platform_ids=platform_ids,
            concept_links=(),
            knowledge_context_snapshot=snapshot,
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


def build_content_strategy_tools(
    organization,
    creator_id: str | None = None,
    mission_id: str | None = None,
    agent_context=None,
) -> list[Tool]:
    tools = [_analyze_tool(organization, mission_id=mission_id)]
    if creator_id:
        tools.append(
            _create_brief_tool(
                organization,
                creator_id,
                mission_id=mission_id,
                agent_context=agent_context,
            )
        )
    return tools


def run_content_strategy_agent(
    *, organization, creator_id: str | None = None, approvals=None, mission_id: str | None = None,
) -> Any:
    creator_id_value = None
    try:
        creator_id_value = int(creator_id) if creator_id else None
    except (TypeError, ValueError):
        creator_id_value = None
    root_context = None
    strategy_context = None
    idempotency_key = (
        f"content-strategy:{organization.id}:{mission_id}"
        if mission_id
        else f"content-strategy:{organization.id}:{timezone.now().date()}"
    )
    existing_run = AgentRun.objects.filter(
        organization=organization,
        idempotency_key=idempotency_key,
    ).first()
    if mission_id:
        mission = GrowthMission.objects.select_related("primary_product").get(
            organization=organization,
            id=mission_id,
        )
        has_social_channels = bool(
            [code for code in mission.allowed_channels if code != "EMAIL"]
        )
        if existing_run is not None and existing_run.knowledge_context_snapshot_id:
            root_context = load_agent_context(
                organization=organization,
                mission=mission,
                snapshot_id=existing_run.knowledge_context_snapshot_id,
            )
        elif existing_run is not None and has_social_channels:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_REQUIRED",
                "Mission AgentRun has no frozen knowledge context.",
            )
        elif existing_run is None and has_social_channels:
            root_context = load_or_build_agent_context(
                organization=organization,
                mission=mission,
                actor=mission.created_by,
            )
        if root_context is not None:
            strategy_context = root_context.for_purpose(
                AgentContextPurpose.CONTENT_STRATEGY
            )
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
    fallback = DeterministicPlanner(actions)
    proposed_execution = resolve_agent_execution(
        organization=organization,
        fallback=fallback,
        allow_llm=True,
    )
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=idempotency_key,
        defaults={
            "goal": "content strategy",
            "agent_type": "content_strategy",
            "execution_mode": proposed_execution.mode,
            "planner_provider": proposed_execution.provider,
            "planner_model": proposed_execution.model,
            "resume_args": {"creator_id": creator_id, "mission_id": mission_id},
            "knowledge_context_snapshot_id": (
                root_context.snapshot_id if root_context is not None else None
            ),
            "created_by_id": creator_id_value,
            "max_steps": 5,
        },
    )
    if root_context is not None and run.knowledge_context_snapshot_id != root_context.snapshot_id:
        raise KnowledgeContextError(
            "KNOWLEDGE_CONTEXT_MISMATCH",
            "Content strategy run is bound to a different knowledge context.",
        )
    tools = ToolRegistry(
        build_content_strategy_tools(
            organization,
            creator_id=creator_id,
            mission_id=mission_id,
            agent_context=strategy_context,
        )
    )
    execution = resolve_run_execution(run=run, fallback=fallback, allow_llm=True)
    return continue_agent_run(
        run=run,
        planner=execution.planner,
        tools=tools,
        approvals=approvals,
    )
