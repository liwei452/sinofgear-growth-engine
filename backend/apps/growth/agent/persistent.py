"""Django-persistent agent run orchestration."""

from __future__ import annotations

from django.db import transaction

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


@transaction.atomic
def continue_agent_run(
    *,
    run: AgentRun,
    planner: Planner,
    tools: ToolRegistry,
    approvals: set[str] | None = None,
) -> AgentRunResult:
    run = AgentRun.objects.select_for_update().get(pk=run.pk)
    memory, completed = load_run_memory(run)
    if run.status == AgentRun.Status.REJECTED:
        return AgentRunResult(
            status="rejected",
            steps=memory.events,
            terminal_reason=run.terminal_reason or "Rejected by reviewer.",
        )
    if run.status == AgentRun.Status.COMPLETED:
        return AgentRunResult(
            status="completed",
            steps=memory.events,
            terminal_reason=run.terminal_reason or "complete",
        )
    existing_count = run.steps.count()
    runtime = AgentRuntime(planner=planner, tools=tools, max_steps=run.max_steps)
    result = runtime.run(
        goal=run.goal,
        memory=memory,
        approvals=approvals,
        completed_action_keys=completed,
        start_index=existing_count,
    )
    for step in result.steps[existing_count:]:
        AgentRunStep.objects.create(
            organization=run.organization,
            run=run,
            index=step.index,
            tool_name=step.tool_name or "",
            args=step.args or {},
            outcome=step.outcome,
            output=step.output,
            error=step.error or "",
            reasoning=step.reasoning,
            approval_token=step.approval_token or "",
            executed_by=run.created_by,
        )
    run.status = _status_from_result(result)
    run.terminal_reason = result.terminal_reason or ""
    run.save(update_fields=["status", "terminal_reason", "updated_at"])
    return result
