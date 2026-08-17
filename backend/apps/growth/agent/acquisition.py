"""Proactive acquisition pipeline wired as an agent-run goal."""

from __future__ import annotations

from typing import Any

from django.conf import settings

from integrations.sources.base import SourceAdapterError

from .persistent import continue_agent_run
from .planner import DeterministicPlanner, Plan, build_planner
from .tools import Tool, ToolRegistry, ToolResult
from ..email_verification import verify_email
from ..enrichment import add_candidate_to_follow_up, prepare_candidate_enrichment
from ..lead_judgment import judge_candidate
from ..maps_discovery import (
    MapsDiscoveryMissingKey,
    MapsDiscoveryNotEnabled,
    run_maps_discovery,
)
from ..models import (
    AgentRun,
    CandidateEnrichmentSnapshot,
    DiscoveryCandidate,
    GoogleMapsDiscoveryConfig,
    TargetAccount,
)
from ..outreach_events import record_sent
from ..services import create_outreach_draft
from ..website_enrichment import prepare_website_enrichment


def _candidate(organization, args: dict[str, Any]) -> DiscoveryCandidate | None:
    candidate_id = args.get("candidate_id")
    if not candidate_id:
        return None
    try:
        return DiscoveryCandidate.objects.get(organization=organization, id=candidate_id)
    except DiscoveryCandidate.DoesNotExist:
        return None


def _discover_maps_tool(organization, source_factory) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        config = GoogleMapsDiscoveryConfig.objects.filter(
            organization=organization,
            enabled=True,
        ).order_by("id").first()
        if config is None:
            return ToolResult(ok=False, error="no enabled Google Maps discovery config.")
        try:
            result = run_maps_discovery(
                config.id,
                trigger="MANUAL",
                source_factory=source_factory,
            )
        except (MapsDiscoveryMissingKey, MapsDiscoveryNotEnabled, SourceAdapterError) as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output=result)

    return Tool(
        name="discover_maps_candidates",
        description="Discover candidate companies from Google Maps for the organization.",
        parameters={"type": "object", "properties": {}},
        risk="read",
        func=func,
    )


def _account_for_candidate(organization, candidate: DiscoveryCandidate) -> TargetAccount | None:
    try:
        return TargetAccount.objects.get(
            organization=organization,
            source_identity=f"candidate:{candidate.id}",
        )
    except TargetAccount.DoesNotExist:
        return None


def _enrich_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        snapshot, created = prepare_candidate_enrichment(candidate=candidate)
        return ToolResult(
            ok=True,
            output={"candidate_id": str(candidate.id), "mode": snapshot.mode, "created": created},
        )

    return Tool(
        name="enrich_candidate",
        description="Build an evidence snapshot from the candidate's imported facts.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _website_enrich_tool(organization, transport) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        if not candidate.website:
            return ToolResult(ok=True, output={"skipped": True, "reason": "no_website"})
        snapshot, created = prepare_website_enrichment(candidate=candidate, transport=transport)
        return ToolResult(
            ok=True,
            output={
                "candidate_id": str(candidate.id),
                "mode": snapshot.mode,
                "facts": snapshot.facts,
                "public_contact_paths": snapshot.public_contact_paths,
                "created": created,
            },
        )

    return Tool(
        name="website_enrich_candidate",
        description="Read the candidate website and extract public facts, signals, and contacts.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _verify_contacts_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        snapshot = CandidateEnrichmentSnapshot.objects.filter(candidate=candidate).first()
        if snapshot is None:
            return ToolResult(ok=False, error="no enrichment snapshot.")
        emails = []
        for path in snapshot.public_contact_paths or []:
            if isinstance(path, dict):
                label = str(path.get("label") or "")
                if "@" in label:
                    emails.append(label)
        verifications = [verify_email(email) for email in emails]
        return ToolResult(
            ok=True,
            output={"emails": emails, "verifications": verifications},
        )

    return Tool(
        name="verify_candidate_contacts",
        description="Verify candidate email addresses discovered during enrichment.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _judge_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        return ToolResult(ok=True, output=judge_candidate(candidate))

    return Tool(
        name="judge_candidate",
        description="Judge the candidate's industry and gear-buyer fit.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _add_to_follow_up_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        account, follow_up, created = add_candidate_to_follow_up(candidate=candidate)
        return ToolResult(
            ok=True,
            output={
                "account_id": str(account.id),
                "follow_up_id": str(follow_up.id),
                "created": created,
            },
        )

    return Tool(
        name="add_to_follow_up",
        description="Resolve the candidate to an account and follow-up record.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _draft_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        account = _account_for_candidate(organization, candidate)
        if account is None:
            return ToolResult(ok=False, error="account not resolved yet.")
        draft, created = create_outreach_draft(account=account)
        return ToolResult(
            ok=True,
            output={
                "account_id": str(account.id),
                "draft_id": str(draft.id),
                "english_draft": draft.english_draft,
                "created": created,
            },
        )

    return Tool(
        name="draft_outreach",
        description="Create a human-reviewable development email draft.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def _send_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate = _candidate(organization, args)
        if candidate is None:
            return ToolResult(ok=False, error="candidate_id not found.")
        account = _account_for_candidate(organization, candidate)
        if account is None:
            return ToolResult(ok=False, error="account not resolved yet.")
        draft = account.outreach_drafts.order_by("-created_at", "-id").first()
        if draft is None:
            return ToolResult(ok=False, error="no outreach draft to send.")
        email = args.get("email") or "outreach@example.com"
        message = record_sent(account=account, draft=draft, email=email)
        return ToolResult(
            ok=True,
            output={
                "account_id": str(account.id),
                "draft_id": str(draft.id),
                "message_id": message.provider_message_id,
                "provider": message.provider,
                "status": message.status,
            },
        )

    return Tool(
        name="send_email",
        description="Send the approved development email (requires human approval).",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="write",
        func=func,
    )


def build_proactive_acquisition_tools(
    organization,
    *,
    website_transport=None,
    maps_source_factory=None,
) -> list[Tool]:
    return [
        _discover_maps_tool(organization, maps_source_factory),
        _enrich_tool(organization),
        _website_enrich_tool(organization, website_transport),
        _verify_contacts_tool(organization),
        _judge_tool(organization),
        _add_to_follow_up_tool(organization),
        _draft_tool(organization),
        _send_tool(organization),
    ]


def proactive_acquisition_plan(candidate_id: str) -> list[Plan]:
    args = {"candidate_id": candidate_id}
    return [
        Plan(reasoning="build facts", tool_name="enrich_candidate", tool_args=args),
        Plan(reasoning="judge fit", tool_name="judge_candidate", tool_args=args),
        Plan(reasoning="resolve account", tool_name="add_to_follow_up", tool_args=args),
        Plan(reasoning="draft email", tool_name="draft_outreach", tool_args=args),
        Plan(reasoning="send email", tool_name="send_email", tool_args=args),
    ]


def proactive_acquisition_website_plan(candidate_id: str) -> list[Plan]:
    args = {"candidate_id": candidate_id}
    return [
        Plan(reasoning="build facts", tool_name="enrich_candidate", tool_args=args),
        Plan(reasoning="read website", tool_name="website_enrich_candidate", tool_args=args),
        Plan(reasoning="verify contacts", tool_name="verify_candidate_contacts", tool_args=args),
        Plan(reasoning="resolve account", tool_name="add_to_follow_up", tool_args=args),
        Plan(reasoning="draft email", tool_name="draft_outreach", tool_args=args),
        Plan(reasoning="send email", tool_name="send_email", tool_args=args),
    ]


def run_proactive_acquisition(
    *,
    organization,
    candidate_id: str,
    approvals: set[str] | None = None,
    website_transport=None,
) -> Any:
    provider_code = getattr(settings, "PRODUCT_AI_PROVIDER", "fake")
    candidate = DiscoveryCandidate.objects.filter(
        organization=organization,
        id=candidate_id,
    ).first()
    if candidate is None:
        raise DiscoveryCandidate.DoesNotExist
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=f"proactive:{candidate_id}",
        defaults={
            "goal": f"proactive acquisition for candidate {candidate_id}",
            "max_steps": 20,
        },
    )
    tools = ToolRegistry(
        build_proactive_acquisition_tools(organization, website_transport=website_transport)
    )
    plan = (
        proactive_acquisition_website_plan(candidate_id)
        if candidate.website
        else proactive_acquisition_plan(candidate_id)
    )
    fallback = DeterministicPlanner(plan)
    planner = build_planner(provider_code=provider_code, fallback=fallback)
    return continue_agent_run(run=run, planner=planner, tools=tools, approvals=approvals)


def resume_proactive_acquisition(
    *,
    organization,
    candidate_id: str,
    approval_token: str,
    website_transport=None,
) -> Any:
    candidate = DiscoveryCandidate.objects.get(organization=organization, id=candidate_id)
    run = AgentRun.objects.get(
        organization=organization,
        idempotency_key=f"proactive:{candidate_id}",
    )
    tools = ToolRegistry(
        build_proactive_acquisition_tools(organization, website_transport=website_transport)
    )
    plan = (
        proactive_acquisition_website_plan(candidate_id)
        if candidate.website
        else proactive_acquisition_plan(candidate_id)
    )
    planner = DeterministicPlanner(plan)
    return continue_agent_run(
        run=run,
        planner=planner,
        tools=tools,
        approvals={approval_token},
    )


def run_proactive_acquisition_day(
    *,
    organization,
    limit: int = 50,
    approvals: set[str] | None = None,
    website_transport=None,
) -> dict[str, Any]:
    candidate_ids = list(
        DiscoveryCandidate.objects.filter(
            organization=organization,
            status=DiscoveryCandidate.Status.ACCEPTED,
        )
        .order_by("-score", "-created_at", "-id")
        .values_list("id", flat=True)[:limit]
    )
    summary: dict[str, Any] = {
        "candidates": len(candidate_ids),
        "waiting_approval": 0,
        "completed": 0,
        "failed": 0,
        "pending_approvals": [],
    }
    for candidate_id in candidate_ids:
        result = run_proactive_acquisition(
            organization=organization,
            candidate_id=str(candidate_id),
            approvals=approvals,
            website_transport=website_transport,
        )
        if result.status == "waiting_approval":
            summary["waiting_approval"] += 1
            summary["pending_approvals"].append(
                {
                    "candidate_id": str(candidate_id),
                    "approval_token": result.pending_approval.approval_token,
                }
            )
        elif result.status == "completed":
            summary["completed"] += 1
        else:
            summary["failed"] += 1
    return summary
