"""Agent tools and runner for the customer-service front desk."""

from __future__ import annotations

from typing import Any

from .persistent import continue_agent_run
from .planner import DeterministicPlanner, Plan
from .tools import Tool, ToolRegistry, ToolResult
from ..customer_service import (
    draft_reply,
    lead_context,
    product_knowledge,
    record_customer_service_turn,
)
from ..models import AgentRun, InboundLead


def _lead(organization, lead_id: str) -> InboundLead | None:
    try:
        return InboundLead.objects.get(organization=organization, id=lead_id)
    except InboundLead.DoesNotExist:
        return None


def _context_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        lead = _lead(organization, args.get("lead_id", ""))
        if lead is None:
            return ToolResult(ok=False, error="lead_id not found.")
        return ToolResult(ok=True, output=lead_context(lead))

    return Tool(
        name="lookup_lead_context",
        description="Look up the inbound lead's contact, need, and intent context.",
        parameters={
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
        risk="read",
        func=func,
    )


def _knowledge_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        lead = _lead(organization, args.get("lead_id", ""))
        if lead is None:
            return ToolResult(ok=False, error="lead_id not found.")
        context = lead_context(lead)
        return ToolResult(
            ok=True,
            output={"knowledge": product_knowledge(organization, context["need_slug"])},
        )

    return Tool(
        name="lookup_product_knowledge",
        description="Look up product or capability knowledge for the lead's need.",
        parameters={
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
        risk="read",
        func=func,
    )


def _draft_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        lead = _lead(organization, args.get("lead_id", ""))
        if lead is None:
            return ToolResult(ok=False, error="lead_id not found.")
        return ToolResult(
            ok=True,
            output={"draft_reply": draft_reply(organization, lead_context(lead))},
        )

    return Tool(
        name="draft_customer_reply",
        description="Draft a customer-service reply from the lead context and knowledge.",
        parameters={
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
        risk="read",
        func=func,
    )


def _decision_tool(organization) -> Tool:
    def func(args: dict[str, Any]) -> ToolResult:
        lead = _lead(organization, args.get("lead_id", ""))
        if lead is None:
            return ToolResult(ok=False, error="lead_id not found.")
        turn = record_customer_service_turn(lead=lead)
        return ToolResult(
            ok=True,
            output={
                "decision": turn.decision,
                "draft_reply": turn.draft_reply,
                "reasoning": turn.reasoning,
            },
        )

    return Tool(
        name="decide_escalation",
        description="Decide auto-reply or human escalation and record the service turn.",
        parameters={
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
        risk="read",
        func=func,
    )


def build_customer_service_tools(organization) -> list[Tool]:
    return [
        _context_tool(organization),
        _knowledge_tool(organization),
        _draft_tool(organization),
        _decision_tool(organization),
    ]


def customer_service_plan(lead_id: str) -> list[Plan]:
    args = {"lead_id": lead_id}
    return [
        Plan(reasoning="look up lead", tool_name="lookup_lead_context", tool_args=args),
        Plan(reasoning="look up knowledge", tool_name="lookup_product_knowledge", tool_args=args),
        Plan(reasoning="draft reply", tool_name="draft_customer_reply", tool_args=args),
        Plan(reasoning="decide escalation", tool_name="decide_escalation", tool_args=args),
    ]


def run_customer_service_agent(*, organization, lead_id: str) -> Any:
    run, _ = AgentRun.objects.get_or_create(
        organization=organization,
        idempotency_key=f"customer-service:{lead_id}",
        defaults={"goal": f"customer service for lead {lead_id}", "max_steps": 20},
    )
    tools = ToolRegistry(build_customer_service_tools(organization))
    planner = DeterministicPlanner(customer_service_plan(lead_id))
    return continue_agent_run(run=run, planner=planner, tools=tools)
