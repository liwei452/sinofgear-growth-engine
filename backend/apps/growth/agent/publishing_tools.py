"""Social-operations agent tools that reuse the existing publishing pipeline."""

from __future__ import annotations

from typing import Any

from django.utils.dateparse import parse_datetime

from apps.content.models import PlatformContent
from apps.platforms.models import SocialAccount
from apps.publishing.models import PublishedPost
from apps.publishing.services import PublishingConflict, create_publish_task

from .persistent import continue_agent_run
from .execution import resolve_agent_execution, resolve_run_execution
from .planner import DeterministicPlanner, Plan
from .tools import Tool, ToolRegistry, ToolResult
from ..models import AgentRun


def _get_content(organization, content_id: str) -> PlatformContent | None:
    return PlatformContent.objects.filter(id=content_id, organization=organization).first()


def _get_account(organization, account_id: str) -> SocialAccount | None:
    return SocialAccount.objects.filter(id=account_id, organization=organization).first()


def _propose_calendar(organization) -> list[dict[str, str]]:
    contents = PlatformContent.objects.filter(
        organization=organization,
        status=PlatformContent.Status.APPROVED,
    ).select_related("platform")[:20]
    return [
        {"content_id": str(content.id), "platform_code": content.platform.code}
        for content in contents
    ]


def _summarize_performance(organization) -> dict[str, Any]:
    from django.db.models import Sum

    from apps.tracking.models import ClickEvent

    from ..models import CRMHandoff, InboundRfq
    from apps.publishing.models import PostMetric

    posts = PublishedPost.objects.filter(organization=organization)
    metric_totals = PostMetric.objects.filter(
        post__organization=organization
    ).exclude(source="demo").aggregate(
        impressions=Sum("impressions"),
        plays=Sum("plays"),
        likes=Sum("likes"),
        comments=Sum("comments"),
        shares=Sum("shares"),
    )
    impressions = metric_totals["impressions"] or 0
    plays = metric_totals["plays"] or 0
    click_count = ClickEvent.objects.filter(
        tracking_link__organization=organization
    ).count()
    inquiry_count = InboundRfq.objects.filter(organization=organization).count()
    recommendations = []
    if impressions == 0:
        recommendations.append(
            "No impressions yet; publish consistently and verify platform credentials."
        )
    elif plays == 0:
        recommendations.append(
            "Impressions exist but no video plays; consider short-video formats for wider reach."
        )
    if impressions > 0 and click_count == 0:
        recommendations.append(
            "Low click-through; strengthen the CTA and landing-page value."
        )
    if click_count > 0 and inquiry_count == 0:
        recommendations.append(
            "Clicks are coming but no inquiries; simplify the RFQ/quote path."
        )
    return {
        "published_count": posts.count(),
        "impressions": impressions,
        "plays": plays,
        "likes": metric_totals["likes"] or 0,
        "comments": metric_totals["comments"] or 0,
        "shares": metric_totals["shares"] or 0,
        "click_count": click_count,
        "inquiry_count": inquiry_count,
        "crm_handoff_count": CRMHandoff.objects.filter(
            organization=organization
        ).count(),
        "recommendations": recommendations,
    }


def _propose_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, output={"proposals": _propose_calendar(organization)})

    return Tool(
        name="propose_publish_calendar",
        description="Propose a publish calendar from approved platform content.",
        parameters={"type": "object", "properties": {}},
        risk="read",
        func=func,
    )


def _performance_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, output=_summarize_performance(organization))

    return Tool(
        name="analyze_post_performance",
        description="Summarize published post performance.",
        parameters={"type": "object", "properties": {}},
        risk="read",
        func=func,
    )


def _schedule_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        content = _get_content(organization, args.get("content_id", ""))
        if content is None:
            return ToolResult(ok=False, error="content_id not found.")
        account = _get_account(organization, args.get("account_id", ""))
        if account is None:
            return ToolResult(ok=False, error="account_id not found.")
        scheduled_at = args.get("scheduled_at")
        if isinstance(scheduled_at, str):
            scheduled_at = parse_datetime(scheduled_at)
            if scheduled_at is None:
                return ToolResult(ok=False, error="scheduled_at is not a valid datetime.")
        key = args.get("idempotency_key") or (
            f"publish:{content.id}:{account.id}:{args.get('scheduled_at', '')}"
        )
        try:
            task = create_publish_task(
                content=content,
                account=account,
                idempotency_key=key,
                scheduled_at=scheduled_at,
                timezone_name=args.get("timezone_name", "UTC"),
                connector_code="mock",
            )
        except (PublishingConflict, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output={"publish_task_id": str(task.id), "status": task.status})

    return Tool(
        name="schedule_social_post",
        description="Schedule an approved platform content for publishing.",
        parameters={
            "type": "object",
            "properties": {
                "content_id": {"type": "string"},
                "account_id": {"type": "string"},
                "scheduled_at": {"type": "string"},
                "timezone_name": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            "required": ["content_id", "account_id"],
        },
        risk="write",
        func=func,
    )


def build_social_ops_tools(organization) -> list[Tool]:
    return [
        _propose_tool(organization),
        _schedule_tool(organization),
        _performance_tool(organization),
    ]


def run_social_ops_agent(
    *,
    organization,
    content_id: str,
    account_id: str,
    scheduled_at: str | None = None,
    timezone_name: str = "UTC",
    idempotency_key: str | None = None,
    approvals: set[str] | None = None,
) -> Any:
    fallback = DeterministicPlanner(
        [
            Plan(
                reasoning="summarize published post performance",
                tool_name="analyze_post_performance",
                tool_args={},
            ),
            Plan(
                reasoning="propose a publish calendar from approved content",
                tool_name="propose_publish_calendar",
                tool_args={},
            ),
            Plan(
                reasoning="schedule approved social post",
                tool_name="schedule_social_post",
                tool_args={
                    "content_id": content_id,
                    "account_id": account_id,
                    "scheduled_at": scheduled_at,
                    "timezone_name": timezone_name,
                    "idempotency_key": idempotency_key,
                },
            ),
        ]
    )
    proposed_execution = resolve_agent_execution(
        organization=organization,
        fallback=fallback,
        allow_llm=True,
    )
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=(
            idempotency_key
            or f"social-ops:{content_id}:{account_id}:{scheduled_at or 'immediate'}"
        ),
        defaults={
            "goal": "social publishing",
            "agent_type": "social_ops",
            "execution_mode": proposed_execution.mode,
            "planner_provider": proposed_execution.provider,
            "planner_model": proposed_execution.model,
            "resume_args": {
                "content_id": content_id,
                "account_id": account_id,
                "scheduled_at": scheduled_at,
                "timezone_name": timezone_name,
                "idempotency_key": idempotency_key,
            },
            "max_steps": 5,
        },
    )
    tools = ToolRegistry(build_social_ops_tools(organization))
    execution = resolve_run_execution(
        run=run,
        fallback=fallback,
        allow_llm=True,
    )
    return continue_agent_run(
        run=run,
        planner=execution.planner,
        tools=tools,
        approvals=approvals,
    )
