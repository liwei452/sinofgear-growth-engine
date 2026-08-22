"""Adapters that expose existing growth capabilities as agent tools."""

from __future__ import annotations

from typing import Any

from .tools import Tool, ToolResult
from ..buying_signals import detect_buying_signals
from ..company_resolution import normalize_company_name
from ..contact_intelligence import extract_team_contacts
from ..email_verification_services import verify_email_for_tenant
from ..grading import grade_candidate
from ..lead_judgment import judge_candidate
from ..models import DiscoveryCandidate


def _grade(args: dict[str, Any]) -> ToolResult:
    total, grade, breakdown = grade_candidate(
        primary_type=args.get("primary_type", ""),
        types=tuple(args.get("types", [])),
        website=args.get("website", ""),
        country=args.get("country", ""),
    )
    return ToolResult(ok=True, output={"score": total, "grade": grade, "breakdown": breakdown})


def _detect_signals(args: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, output={"signals": detect_buying_signals(args.get("text", ""))})


def _normalize_name(args: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, output={"normalized": normalize_company_name(args.get("name", ""))})


def _verify_email_tool(organization) -> Tool:
    organization_id = organization.id

    def func(args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            output={
                "verification": verify_email_for_tenant(
                    organization_id=organization_id,
                    email=args.get("email", ""),
                )
            },
        )

    return Tool(
        name="verify_email",
        description="Run an audited local-first email verification.",
        parameters={
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
        risk="write",
        approval_required=False,
        func=func,
    )


def _extract_contacts(args: dict[str, Any]) -> ToolResult:
    return ToolResult(
        ok=True,
        output={"contacts": extract_team_contacts(args.get("html", ""), args.get("base_url", ""))},
    )


def _judge_candidate_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        candidate_id = args.get("candidate_id")
        if not candidate_id:
            return ToolResult(ok=False, error="candidate_id is required.")
        try:
            candidate = DiscoveryCandidate.objects.get(organization=organization, id=candidate_id)
        except DiscoveryCandidate.DoesNotExist:
            return ToolResult(ok=False, error="Candidate not found.")
        return ToolResult(ok=True, output=judge_candidate(candidate))

    return Tool(
        name="judge_candidate",
        description="Judge a candidate's industry and gear-buyer fit.",
        parameters={
            "type": "object",
            "properties": {"candidate_id": {"type": "string"}},
            "required": ["candidate_id"],
        },
        risk="read",
        func=func,
    )


def build_pipeline_tools(*, organization=None) -> list[Tool]:
    tools = [
        Tool(
            name="grade_candidate",
            description="Score industrial gear and transmission buyer fit.",
            parameters={
                "type": "object",
                "properties": {
                    "primary_type": {"type": "string"},
                    "types": {"type": "array", "items": {"type": "string"}},
                    "website": {"type": "string"},
                    "country": {"type": "string"},
                },
            },
            risk="read",
            func=_grade,
        ),
        Tool(
            name="detect_buying_signals",
            description="Detect industrial buying or maintenance signals in text.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            risk="read",
            func=_detect_signals,
        ),
        Tool(
            name="normalize_company_name",
            description="Normalize a company name for identity resolution.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            risk="read",
            func=_normalize_name,
        ),
        Tool(
            name="extract_team_contacts",
            description="Extract public contact emails and role hints from HTML.",
            parameters={
                "type": "object",
                "properties": {
                    "html": {"type": "string"},
                    "base_url": {"type": "string"},
                },
                "required": ["html"],
            },
            risk="read",
            func=_extract_contacts,
        ),
    ]
    if organization is not None:
        tools.append(_verify_email_tool(organization))
        tools.append(_judge_candidate_tool(organization))
    return tools
