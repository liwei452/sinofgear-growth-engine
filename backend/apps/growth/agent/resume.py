"""Generic approval-resume dispatch for agent runs."""

from __future__ import annotations

from ..models import AgentRun


def resume_agent_run(*, run: AgentRun, approval_token: str):
    from .acquisition import resume_proactive_acquisition
    from .content_creation_tools import (
        run_content_creation_agent,
        run_platform_variants_agent,
    )
    from .content_tools import run_content_strategy_agent
    from .customer_service_tools import run_customer_service_agent
    from .publishing_tools import run_social_ops_agent

    organization = run.organization
    args = run.resume_args or {}
    agent_type = run.agent_type

    if agent_type == "proactive":
        return resume_proactive_acquisition(
            organization=organization,
            candidate_id=args["candidate_id"],
            approval_token=approval_token,
        )
    if agent_type == "content_strategy":
        return run_content_strategy_agent(
            organization=organization,
            creator_id=args.get("creator_id"),
            approvals={approval_token},
        )
    if agent_type == "content_creation":
        return run_content_creation_agent(
            organization=organization,
            brief_id=args["brief_id"],
            actor_id=args["actor_id"],
            values=args["values"],
            product_id=args["product_id"],
            platform_id=args["platform_id"],
            asset_ids=args.get("asset_ids"),
            approvals={approval_token},
        )
    if agent_type == "platform_variants":
        return run_platform_variants_agent(
            organization=organization,
            master_id=args["master_id"],
            actor_id=args["actor_id"],
            approvals={approval_token},
        )
    if agent_type == "social_ops":
        return run_social_ops_agent(
            organization=organization,
            content_id=args["content_id"],
            account_id=args["account_id"],
            scheduled_at=args.get("scheduled_at"),
            timezone_name=args.get("timezone_name", "UTC"),
            idempotency_key=args.get("idempotency_key"),
            approvals={approval_token},
        )
    if agent_type == "customer_service":
        return run_customer_service_agent(
            organization=organization,
            rfq_id=args["rfq_id"],
        )
    raise ValueError(f"Unknown agent type {agent_type!r}.")
