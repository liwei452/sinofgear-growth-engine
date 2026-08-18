"""Resolve and preserve the truthful execution identity of an Agent run."""

from __future__ import annotations

from dataclasses import dataclass

from apps.ai.provider_config import resolve_product_ai

from ..models import AgentRun
from .planner import LLMPlanner, Planner


class PlannerConfigurationUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class AgentExecution:
    mode: str
    provider: str
    model: str
    planner: Planner


def resolve_agent_execution(*, organization, fallback: Planner, allow_llm: bool) -> AgentExecution:
    runtime = resolve_product_ai(organization)
    if allow_llm and runtime.real_requests_enabled:
        return AgentExecution(
            mode=AgentRun.ExecutionMode.AI_AGENT,
            provider=runtime.provider_code,
            model=runtime.model,
            planner=LLMPlanner(provider=runtime.provider),
        )
    return AgentExecution(
        mode=AgentRun.ExecutionMode.AUTOMATION,
        provider="",
        model="",
        planner=fallback,
    )


def resolve_run_execution(
    *, run: AgentRun, fallback: Planner, allow_llm: bool,
) -> AgentExecution:
    if run.status in {AgentRun.Status.COMPLETED, AgentRun.Status.REJECTED}:
        return AgentExecution(
            mode=run.execution_mode,
            provider=run.planner_provider,
            model=run.planner_model,
            planner=fallback,
        )
    if run.execution_mode != AgentRun.ExecutionMode.AI_AGENT:
        return AgentExecution(
            mode=run.execution_mode,
            provider=run.planner_provider,
            model=run.planner_model,
            planner=fallback,
        )
    if not allow_llm:
        raise PlannerConfigurationUnavailable(
            "Persisted AI planner configuration is unavailable for this run."
        )
    runtime = resolve_product_ai(run.organization)
    if (
        not runtime.real_requests_enabled
        or runtime.provider_code != run.planner_provider
        or runtime.model != run.planner_model
    ):
        raise PlannerConfigurationUnavailable(
            "Persisted planner configuration is unavailable; the run was not resumed."
        )
    return AgentExecution(
        mode=run.execution_mode,
        provider=run.planner_provider,
        model=run.planner_model,
        planner=LLMPlanner(provider=runtime.provider),
    )
