"""Bounded tool abstractions for the growth agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: str
    func: Callable[[dict[str, Any]], ToolResult]
    approval_required: bool | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Tool name must not be blank.")
        if self.risk not in {"read", "write"}:
            raise ValueError("Tool risk must be 'read' or 'write'.")

    @property
    def requires_approval(self) -> bool:
        if self.approval_required is not None:
            return self.approval_required
        return self.risk == "write"

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "risk": self.risk,
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool '{name}'.") from exc

    def descriptors(self) -> list[dict[str, Any]]:
        return [tool.descriptor() for tool in self._tools.values()]
