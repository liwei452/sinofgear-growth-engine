"""Agent tools for routing inbound leads."""

from __future__ import annotations

from typing import Any

from .tools import Tool, ToolResult
from ..inbound_triage import triage_inbound_lead
from ..models import InboundLead


def _triage_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        lead_id = args.get("lead_id")
        if not lead_id:
            return ToolResult(ok=False, error="lead_id is required.")
        try:
            lead = InboundLead.objects.get(organization=organization, id=lead_id)
        except InboundLead.DoesNotExist:
            return ToolResult(ok=False, error="Inbound lead not found.")
        lead = triage_inbound_lead(lead=lead)
        return ToolResult(
            ok=True,
            output={
                "lead_id": str(lead.id),
                "route": lead.route,
                "route_reason": lead.route_reason,
            },
        )

    return Tool(
        name="triage_inbound_lead",
        description="Route an inbound lead to acquisition or customer service.",
        parameters={
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
        risk="read",
        func=func,
    )


def build_inbound_triage_tools(organization) -> list[Tool]:
    return [_triage_tool(organization)]
