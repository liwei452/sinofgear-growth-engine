"""Planner implementations that choose the agent's next action."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from integrations.ai.providers import provider_registry


PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reasoning": {"type": "string"},
        "tool_name": {"type": ["string", "null"]},
        "tool_args": {"type": ["object", "null"]},
        "terminal_reason": {"type": ["string", "null"]},
    },
    "required": ["reasoning", "tool_name", "tool_args", "terminal_reason"],
}


@dataclass(frozen=True)
class Plan:
    reasoning: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    terminal_reason: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.terminal_reason is not None


class Planner(Protocol):
    def plan(
        self,
        *,
        goal: str,
        memory: dict[str, Any],
        tools: list[dict[str, Any]],
        step_index: int,
    ) -> Plan: ...


class LLMPlanner:
    def __init__(self, provider_code: str) -> None:
        self._provider = provider_registry.get(provider_code)

    def plan(
        self,
        *,
        goal: str,
        memory: dict[str, Any],
        tools: list[dict[str, Any]],
        step_index: int,
    ) -> Plan:
        prompt = "Choose the next bounded action for the growth agent.\n||INPUT:" + json.dumps(
            {
                "goal": goal,
                "step_index": step_index,
                "memory": memory,
                "tools": tools,
            },
            ensure_ascii=False,
        )
        result = self._provider.generate(prompt=prompt, schema=PLAN_SCHEMA)
        tool_args = result.get("tool_args")
        return Plan(
            reasoning=result["reasoning"],
            tool_name=result.get("tool_name"),
            tool_args=tool_args if isinstance(tool_args, dict) else None,
            terminal_reason=result.get("terminal_reason"),
        )


class DeterministicPlanner:
    """A scripted planner for tests and no-LLM environments."""

    def __init__(self, actions: list[Plan]) -> None:
        self._actions = list(actions)

    def plan(
        self,
        *,
        goal: str,
        memory: dict[str, Any],
        tools: list[dict[str, Any]],
        step_index: int,
    ) -> Plan:
        if step_index < len(self._actions):
            return self._actions[step_index]
        return Plan(reasoning="No more scripted actions.", terminal_reason="script exhausted")


def build_planner(*, provider_code: str, fallback: Planner) -> Planner:
    if provider_code == "deepseek":
        return LLMPlanner(provider_code)
    return fallback
