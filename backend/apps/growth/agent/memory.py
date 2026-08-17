"""Append-only memory for a single agent run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentStep:
    index: int
    tool_name: str | None
    args: dict[str, Any] | None
    outcome: str
    output: dict[str, Any] | None
    error: str | None
    reasoning: str
    approval_token: str | None = None


@dataclass
class Memory:
    events: list[AgentStep] = field(default_factory=list)

    def record(self, step: AgentStep) -> None:
        self.events.append(step)

    def snapshot(self) -> dict[str, Any]:
        return {
            "steps": [
                {
                    "index": step.index,
                    "tool_name": step.tool_name,
                    "outcome": step.outcome,
                    "output": step.output,
                    "reasoning": step.reasoning,
                }
                for step in self.events
            ],
        }
