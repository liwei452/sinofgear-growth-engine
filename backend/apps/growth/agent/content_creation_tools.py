"""Content-creation agent tools that reuse the existing content pipeline."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.ai.models import PromptVersion
from apps.ai.runtime import product_ai_status
from apps.assets.models import MaterialAsset
from apps.campaigns.models import ContentBrief
from apps.campaigns.services import (
    build_content_generation_input,
    mark_content_brief_ready,
    update_content_brief,
)
from apps.content.tasks import generate_master_content_job
from apps.content.models import MasterContent
from apps.content.services import ContentStateError, create_platform_content
from apps.identity.models import Membership
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform

from .persistent import continue_agent_run
from .planner import DeterministicPlanner, Plan
from .tools import Tool, ToolRegistry, ToolResult
from ..models import AgentRun


def _actor(organization, actor_id: str):
    actor = get_user_model().objects.filter(id=actor_id).first()
    if actor is None:
        return None, "actor not found."
    if not Membership.objects.filter(user=actor, organization=organization).exists():
        return None, "actor is not a member of this organization."
    return actor, ""


def _user_id(value) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _auto_match_assets(organization, platform_id) -> list[str]:
    platform = Platform.objects.filter(id=platform_id).first()
    if platform is None:
        return []
    code = platform.code.upper()
    if code in {"TIKTOK", "YOUTUBE"}:
        prefixes = ("video/",)
    elif code == "INSTAGRAM":
        prefixes = ("image/", "video/")
    else:
        prefixes = ("image/", "video/", "application/pdf")
    query = Q()
    for prefix in prefixes:
        query |= Q(mime_type__startswith=prefix)
    assets = (
        MaterialAsset.objects.filter(
            organization=organization,
            status=MaterialAsset.Status.ACTIVE,
        )
        .filter(query)
        .order_by("-created_at", "-id")[:5]
    )
    return [str(asset.id) for asset in assets]


def _brief(organization, brief_id: str) -> ContentBrief | None:
    return ContentBrief.objects.filter(id=brief_id, organization=organization).first()


def _get_master(organization, master_id: str) -> MasterContent | None:
    return MasterContent.objects.filter(id=master_id, organization=organization).first()


def _missing_media_requirements(brief) -> list[str]:
    media_platforms = {"INSTAGRAM", "TIKTOK", "YOUTUBE"}
    assets = list(brief.asset_links.select_related("asset"))
    missing = []
    for link in brief.platform_links.select_related("platform"):
        code = link.platform.code.upper()
        if code not in media_platforms:
            continue
        if code in {"TIKTOK", "YOUTUBE"}:
            matched = any(
                (asset_link.asset.mime_type or "").startswith("video/")
                for asset_link in assets
            )
        else:
            matched = any(
                (asset_link.asset.mime_type or "").startswith(("image/", "video/"))
                for asset_link in assets
            )
        if not matched:
            missing.append(code)
    return missing


def _enrich_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        brief = _brief(organization, args.get("brief_id", ""))
        if brief is None:
            return ToolResult(ok=False, error="brief_id not found.")
        values = args.get("values") or {}
        product_ids = args.get("product_ids") or []
        platform_ids = args.get("platform_ids") or []
        asset_ids = args.get("asset_ids") or []
        try:
            brief = update_content_brief(
                brief.id,
                values=values,
                product_ids=product_ids,
                platform_ids=platform_ids,
                asset_ids=asset_ids,
            )
        except ValidationError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(
            ok=True,
            output={
                "brief_id": str(brief.id),
                "status": brief.status,
                "missing_asset_requirements": _missing_media_requirements(brief),
            },
        )

    return Tool(
        name="enrich_content_brief",
        description="Fill brief fields and link product and platform for generation.",
        parameters={
            "type": "object",
            "properties": {
                "brief_id": {"type": "string"},
                "values": {"type": "object"},
                "product_ids": {"type": "array", "items": {"type": "string"}},
                "platform_ids": {"type": "array", "items": {"type": "string"}},
                "asset_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["brief_id"],
        },
        risk="write",
        func=func,
    )


def _mark_ready_tool(organization, actor_id: str) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        brief = _brief(organization, args.get("brief_id", ""))
        if brief is None:
            return ToolResult(ok=False, error="brief_id not found.")
        actor, error = _actor(organization, actor_id)
        if error:
            return ToolResult(ok=False, error=error)
        try:
            brief = mark_content_brief_ready(brief.id, reviewer=actor)
        except ValidationError as exc:
            return ToolResult(ok=False, error=str(exc))
        return ToolResult(ok=True, output={"brief_id": str(brief.id), "status": brief.status})

    return Tool(
        name="mark_content_brief_ready",
        description="Mark an enriched content brief as READY for generation.",
        parameters={
            "type": "object",
            "properties": {"brief_id": {"type": "string"}},
            "required": ["brief_id"],
        },
        risk="write",
        func=func,
    )


def _trigger_tool(organization, actor_id: str) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        brief = _brief(organization, args.get("brief_id", ""))
        if brief is None:
            return ToolResult(ok=False, error="brief_id not found.")
        actor, error = _actor(organization, actor_id)
        if error:
            return ToolResult(ok=False, error=error)
        if brief.status != ContentBrief.Status.READY:
            return ToolResult(ok=False, error="brief must be READY before generation.")
        if product_ai_status()["mode"] == "CONFIGURATION_REQUIRED":
            return ToolResult(ok=False, error="AI provider key is not configured.")
        prompt = PromptVersion.objects.filter(
            purpose="CONTENT_GENERATE",
            status=PromptVersion.Status.PUBLISHED,
        ).order_by("-version").first()
        if prompt is None:
            return ToolResult(ok=False, error="published generation prompt is unavailable.")
        idempotency_key = f"master:{brief.id}:{brief.version}:{prompt.id}"
        job = Job.objects.filter(
            organization=organization,
            type=Job.Type.CONTENT_GENERATE,
            idempotency_key=idempotency_key,
        ).first()
        if job is None:
            snapshot = build_content_generation_input(brief.id).to_dict()
            job = JobService.create(
                organization=organization,
                job_type=Job.Type.CONTENT_GENERATE,
                input_snapshot=snapshot,
                idempotency_key=idempotency_key,
                created_by=actor,
            )
            transaction.on_commit(
                lambda: generate_master_content_job.delay(str(job.id), str(prompt.id))
            )
        return ToolResult(ok=True, output={"job_id": str(job.id), "status": job.status})

    return Tool(
        name="trigger_master_generation",
        description="Create and dispatch the master-content generation job.",
        parameters={
            "type": "object",
            "properties": {"brief_id": {"type": "string"}},
            "required": ["brief_id"],
        },
        risk="write",
        func=func,
    )


def build_content_creation_tools(organization, actor_id: str) -> list[Tool]:
    return [
        _enrich_tool(organization),
        _mark_ready_tool(organization, actor_id),
        _trigger_tool(organization, actor_id),
    ]


def _platform_variants_tool(organization, actor_id: str) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        master = _get_master(organization, args.get("master_id", ""))
        if master is None:
            return ToolResult(ok=False, error="master_id not found.")
        actor, error = _actor(organization, actor_id)
        if error:
            return ToolResult(ok=False, error=error)
        variants = []
        for link in master.brief.platform_links.all():
            try:
                content = create_platform_content(master, platform=link.platform, actor=actor)
            except ContentStateError as exc:
                return ToolResult(ok=False, error=str(exc))
            variants.append(
                {
                    "platform_content_id": str(content.id),
                    "platform_code": link.platform.code,
                    "status": content.status,
                }
            )
        return ToolResult(ok=True, output={"variants": variants})

    return Tool(
        name="create_platform_variants",
        description="Create platform-specific content variants from an approved master.",
        parameters={
            "type": "object",
            "properties": {"master_id": {"type": "string"}},
            "required": ["master_id"],
        },
        risk="write",
        func=func,
    )


def build_platform_variants_tools(organization, actor_id: str) -> list[Tool]:
    return [_platform_variants_tool(organization, actor_id)]


def run_content_creation_agent(
    *,
    organization,
    brief_id: str,
    actor_id: str,
    values: dict[str, Any],
    product_id: str,
    platform_id: str,
    asset_ids: list[str] | None = None,
    approvals=None,
) -> Any:
    if not asset_ids:
        asset_ids = _auto_match_assets(organization, platform_id)
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=f"content-creation:{brief_id}",
        defaults={
            "goal": "content creation",
            "agent_type": "content_creation",
            "resume_args": {
                "brief_id": brief_id,
                "actor_id": actor_id,
                "values": values,
                "product_id": product_id,
                "platform_id": platform_id,
                "asset_ids": asset_ids or [],
            },
            "created_by_id": _user_id(actor_id),
            "max_steps": 10,
        },
    )
    tools = ToolRegistry(build_content_creation_tools(organization, actor_id))
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="enrich brief",
                tool_name="enrich_content_brief",
                tool_args={
                    "brief_id": brief_id,
                    "values": values,
                    "product_ids": [product_id],
                    "platform_ids": [platform_id],
                    "asset_ids": asset_ids or [],
                },
            ),
            Plan(reasoning="mark ready", tool_name="mark_content_brief_ready", tool_args={"brief_id": brief_id}),
            Plan(reasoning="trigger generation", tool_name="trigger_master_generation", tool_args={"brief_id": brief_id}),
        ]
    )
    return continue_agent_run(run=run, planner=planner, tools=tools, approvals=approvals)


def run_platform_variants_agent(
    *, organization, master_id: str, actor_id: str, approvals=None,
) -> Any:
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=f"platform-variants:{master_id}",
        defaults={
            "goal": "platform variants",
            "agent_type": "platform_variants",
            "resume_args": {"master_id": master_id, "actor_id": actor_id},
            "created_by_id": _user_id(actor_id),
            "max_steps": 5,
        },
    )
    tools = ToolRegistry(build_platform_variants_tools(organization, actor_id))
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="create platform variants",
                tool_name="create_platform_variants",
                tool_args={"master_id": master_id},
            )
        ]
    )
    return continue_agent_run(run=run, planner=planner, tools=tools, approvals=approvals)
