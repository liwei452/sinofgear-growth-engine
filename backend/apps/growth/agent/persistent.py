"""Django-persistent agent run orchestration."""

from __future__ import annotations

from django.db import transaction
from apps.common.tenancy import tenant_atomic

from .memory import AgentStep, Memory
from .planner import Planner
from .runtime import AgentRunResult, AgentRuntime, action_key
from .tools import ToolRegistry
from ..models import AgentRun, AgentRunStep


def _status_from_result(result: AgentRunResult) -> str:
    return {
        "completed": AgentRun.Status.COMPLETED,
        "waiting_approval": AgentRun.Status.WAITING_APPROVAL,
        "budget_exceeded": AgentRun.Status.BUDGET_EXCEEDED,
        "failed": AgentRun.Status.FAILED,
    }.get(result.status, AgentRun.Status.FAILED)


def load_run_memory(run: AgentRun) -> tuple[Memory, set[str]]:
    memory = Memory()
    completed: set[str] = set()
    for step in run.steps.all():
        tool_name = step.tool_name or ""
        args = step.args or {}
        memory.record(
            AgentStep(
                index=step.index,
                tool_name=tool_name or None,
                args=args,
                outcome=step.outcome,
                output=step.output,
                error=step.error or None,
                reasoning=step.reasoning or "",
                approval_token=step.approval_token or None,
            )
        )
        if step.outcome == "succeeded":
            completed.add(action_key(tool_name, args))
    return memory, completed


def continue_agent_run(
    *,
    run: AgentRun,
    planner: Planner,
    tools: ToolRegistry,
    approvals: set[str] | None = None,
    organization_id=None,
) -> AgentRunResult:
    def context():
        return (
            tenant_atomic(organization_id)
            if organization_id is not None
            else transaction.atomic()
        )

    with context():
        queryset = AgentRun.objects.select_for_update()
        if organization_id is not None:
            queryset = queryset.filter(organization_id=organization_id)
        locked = queryset.get(pk=run.pk)
        memory, completed = load_run_memory(locked)
        if locked.status == AgentRun.Status.REJECTED:
            return AgentRunResult(
                status="rejected",
                steps=memory.events,
                terminal_reason=locked.terminal_reason or "Rejected by reviewer.",
            )
        if locked.status == AgentRun.Status.COMPLETED:
            return AgentRunResult(
                status="completed",
                steps=memory.events,
                terminal_reason=locked.terminal_reason or "complete",
            )
        run_id = locked.id
        run_updated_at = locked.updated_at
        goal = locked.goal
        max_steps = locked.max_steps
        existing_count = locked.steps.count()
    runtime = AgentRuntime(planner=planner, tools=tools, max_steps=max_steps)
    result = runtime.run(
        goal=goal,
        memory=memory,
        approvals=approvals,
        completed_action_keys=completed,
        start_index=existing_count,
    )
    with context():
        queryset = AgentRun.objects.select_for_update()
        if organization_id is not None:
            queryset = queryset.filter(organization_id=organization_id)
        locked = queryset.get(pk=run_id)
        if locked.updated_at != run_updated_at or locked.steps.count() != existing_count:
            raise RuntimeError("Agent run changed while an external action was in progress.")
        for step in result.steps[existing_count:]:
            AgentRunStep.objects.create(
                organization=locked.organization,
                run=locked,
                index=step.index,
                tool_name=step.tool_name or "",
                args=step.args or {},
                outcome=step.outcome,
                output=step.output,
                error=step.error or "",
                reasoning=step.reasoning,
                approval_token=step.approval_token or "",
                executed_by=locked.created_by,
            )
        locked.status = _status_from_result(result)
        locked.terminal_reason = result.terminal_reason or ""
        locked.save(update_fields=["status", "terminal_reason", "updated_at"])
    return result
