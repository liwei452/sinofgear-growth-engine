from apps.growth.agent.memory import Memory
from apps.growth.agent.planner import DeterministicPlanner, Plan
from apps.growth.agent.runtime import AgentRuntime, action_key
from apps.growth.agent.tools import Tool, ToolRegistry, ToolResult
from apps.ai.services import AIBudgetExceeded


def _read_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"Read {name}",
        parameters={"type": "object"},
        risk="read",
        func=lambda args: ToolResult(ok=True, output={"ran": name}),
    )


def _write_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"Write {name}",
        parameters={"type": "object"},
        risk="write",
        func=lambda args: ToolResult(ok=True, output={"ran": name}),
    )


def test_completes_scripted_plan():
    tools = ToolRegistry([_read_tool("discover"), _read_tool("enrich")])
    planner = DeterministicPlanner(
        [
            Plan(reasoning="find companies", tool_name="discover", tool_args={"country": "VN"}),
            Plan(reasoning="read websites", tool_name="enrich", tool_args={"url": "https://x.example"}),
            Plan(reasoning="all done", terminal_reason="pipeline complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="proactive acquisition", memory=Memory())

    assert result.status == "completed"
    assert result.terminal_reason == "pipeline complete"
    assert [step.tool_name for step in result.steps] == ["discover", "enrich"]


def test_write_tool_pauses_then_resumes_with_approval():
    tools = ToolRegistry([_read_tool("discover"), _write_tool("send_email")])
    planner = DeterministicPlanner(
        [
            Plan(reasoning="find companies", tool_name="discover", tool_args={"country": "VN"}),
            Plan(reasoning="send", tool_name="send_email", tool_args={"to": "a@example.com"}),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    memory = Memory()

    first = runtime.run(goal="proactive acquisition", memory=memory)
    assert first.status == "waiting_approval"
    assert first.pending_approval is not None
    token = first.pending_approval.approval_token
    assert [step.outcome for step in first.steps] == ["succeeded", "blocked_approval"]

    resumed = runtime.run(goal="proactive acquisition", memory=memory, approvals={token})
    assert resumed.status == "completed"
    assert [step.tool_name for step in resumed.steps] == ["discover", "send_email", "discover", "send_email"]
    assert resumed.steps[-1].outcome == "succeeded"


def test_budget_exceeded_when_planner_never_terminates():
    tools = ToolRegistry([_read_tool("ping")])

    class LoopingPlanner:
        def plan(self, *, goal, memory, tools, step_index):
            return Plan(
                reasoning="keep going",
                tool_name="ping",
                tool_args={"n": step_index},
            )

    planner = LoopingPlanner()
    runtime = AgentRuntime(planner=planner, tools=tools, max_steps=3)
    result = runtime.run(goal="run forever", memory=Memory())

    assert result.status == "budget_exceeded"
    assert len(result.steps) == 3


def test_ai_cost_budget_exceeded_surfaces_as_budget_status():
    tools = ToolRegistry([_read_tool("ping")])

    class BudgetBlockedPlanner:
        def plan(self, *, goal, memory, tools, step_index):
            raise AIBudgetExceeded(
                "Organization daily estimated AI cost budget would be exceeded."
            )

    runtime = AgentRuntime(planner=BudgetBlockedPlanner(), tools=tools)
    result = runtime.run(goal="plan with AI", memory=Memory())

    assert result.status == "budget_exceeded"
    assert "cost budget exceeded" in result.terminal_reason


def test_unknown_tool_fails_gracefully():
    tools = ToolRegistry([_read_tool("discover")])
    planner = DeterministicPlanner(
        [Plan(reasoning="bad tool", tool_name="nope", tool_args={})]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="proactive acquisition", memory=Memory())

    assert result.status == "failed"
    assert "Unknown tool" in result.terminal_reason


def test_repeated_action_stops_to_avoid_loop():
    tools = ToolRegistry([_read_tool("discover")])
    planner = DeterministicPlanner(
        [
            Plan(reasoning="first", tool_name="discover", tool_args={}),
            Plan(reasoning="again", tool_name="discover", tool_args={}),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="proactive acquisition", memory=Memory())

    assert result.status == "failed"
    assert "repeated action" in result.terminal_reason


def test_completed_action_is_skipped_on_resume():
    tools = ToolRegistry([_read_tool("discover")])
    planner = DeterministicPlanner(
        [
            Plan(reasoning="find", tool_name="discover", tool_args={"country": "VN"}),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    completed = {action_key("discover", {"country": "VN"})}
    result = runtime.run(goal="resume", memory=Memory(), completed_action_keys=completed)

    assert result.status == "completed"
    assert result.terminal_reason == "complete"
    assert result.steps == []
