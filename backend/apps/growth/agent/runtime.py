"""A bounded, self-directing agent loop with a human approval gate."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .memory import AgentStep, Memory
from .planner import Planner
from .tools import Tool, ToolRegistry, ToolResult


class AgentRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingApproval:
    tool_name: str
    tool_args: dict[str, Any]
    approval_token: str
    reasoning: str


@dataclass
class AgentRunResult:
    status: str
    steps: list[AgentStep] = field(default_factory=list)
    terminal_reason: str | None = None
    pending_approval: PendingApproval | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _approval_token(goal: str, tool_name: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical([goal, tool_name, args]).encode("utf-8")).hexdigest()


def action_key(tool_name: str, args: dict[str, Any]) -> str:
    return _canonical([tool_name, args])


class AgentRuntime:
    def __init__(self, *, planner: Planner, tools: ToolRegistry, max_steps: int = 20) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive.")
        self._planner = planner
        self._tools = tools
        self._max_steps = max_steps

    def run(
        self,
        *,
        goal: str,
        memory: Memory,
        approvals: set[str] | None = None,
        completed_action_keys: set[str] | None = None,
        start_index: int = 0,
    ) -> AgentRunResult:
        approvals = set(approvals or ())
        completed = set(completed_action_keys or ())
        seen_actions: set[str] = set()
        recorded_index = start_index

        for planner_step in range(self._max_steps):
            plan = self._planner.plan(
                goal=goal,
                memory=memory.snapshot(),
                tools=self._tools.descriptors(),
                step_index=planner_step,
            )
            if plan.is_terminal:
                return self._result(
                    status="completed",
                    memory=memory,
                    terminal_reason=plan.terminal_reason,
                )

            tool_name = plan.tool_name or ""
            args = plan.tool_args or {}
            key = action_key(tool_name, args)
            if key in completed:
                # Already completed in a previous run; do not re-execute.
                continue
            if key in seen_actions:
                return self._result(
                    status="failed",
                    memory=memory,
                    terminal_reason=f"Planner repeated action '{tool_name}' without progress.",
                )

            try:
                tool = self._tools.get(tool_name)
            except KeyError as exc:
                memory.record(
                    AgentStep(
                        index=recorded_index,
                        tool_name=tool_name,
                        args=args,
                        outcome="failed",
                        output=None,
                        error=str(exc),
                        reasoning=plan.reasoning,
                    )
                )
                recorded_index += 1
                return self._result(
                    status="failed",
                    memory=memory,
                    terminal_reason=str(exc),
                )

            if tool.requires_approval:
                token = _approval_token(goal, tool_name, args)
                if token not in approvals:
                    step = AgentStep(
                        index=recorded_index,
                        tool_name=tool_name,
                        args=args,
                        outcome="blocked_approval",
                        output=None,
                        error=None,
                        reasoning=plan.reasoning,
                        approval_token=token,
                    )
                    memory.record(step)
                    recorded_index += 1
                    return self._result(
                        status="waiting_approval",
                        memory=memory,
                        pending_approval=PendingApproval(
                            tool_name=tool_name,
                            tool_args=args,
                            approval_token=token,
                            reasoning=plan.reasoning,
                        ),
                    )

            tool_result = self._execute(tool, args)
            outcome = "succeeded" if tool_result.ok else "failed"
            seen_actions.add(key)
            memory.record(
                AgentStep(
                    index=recorded_index,
                    tool_name=tool_name,
                    args=args,
                    outcome=outcome,
                    output=tool_result.output if tool_result.ok else None,
                    error=None if tool_result.ok else tool_result.error,
                    reasoning=plan.reasoning,
                )
            )
            recorded_index += 1
            if not tool_result.ok:
                return self._result(
                    status="failed",
                    memory=memory,
                    terminal_reason=tool_result.error,
                )

        return self._result(
            status="budget_exceeded",
            memory=memory,
            terminal_reason=f"Agent exceeded the {self._max_steps} step budget.",
        )

    @staticmethod
    def _result(
        *,
        status: str,
        memory: Memory,
        terminal_reason: str | None = None,
        pending_approval: PendingApproval | None = None,
    ) -> AgentRunResult:
        return AgentRunResult(
            status=status,
            steps=list(memory.events),
            terminal_reason=terminal_reason,
            pending_approval=pending_approval,
        )

    @staticmethod
    def _execute(tool: Tool, args: dict[str, Any]) -> ToolResult:
        try:
            result = tool.func(args)
        except Exception as exc:  # noqa: BLE001 - boundary for untrusted tool failures
            return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        if not isinstance(result, ToolResult):
            return ToolResult(ok=False, error="Tool returned an unsupported result type.")
        return result
