import pytest

from apps.growth.agent.memory import Memory
from apps.growth.agent.persistent import continue_agent_run
from apps.growth.agent.pipeline_tools import build_pipeline_tools
from apps.growth.agent.planner import DeterministicPlanner, Plan
from apps.growth.agent.runtime import AgentRuntime
from apps.growth.agent.tools import Tool, ToolRegistry, ToolResult
from apps.growth.models import (
    AgentRun,
    DiscoveryCandidate,
    FollowUp,
    OutreachMessage,
    TargetAccount,
)
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Agent", slug="agent")


def _read_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=name,
        parameters={"type": "object"},
        risk="read",
        func=lambda args: ToolResult(ok=True, output={"ran": name}),
    )


def _write_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=name,
        parameters={"type": "object"},
        risk="write",
        func=lambda args: ToolResult(ok=True, output={"ran": name}),
    )


def test_continue_agent_run_persists_and_resumes(organization):
    tools = ToolRegistry([_read_tool("discover"), _write_tool("send_email")])
    planner = DeterministicPlanner(
        [
            Plan(reasoning="find", tool_name="discover", tool_args={"country": "VN"}),
            Plan(reasoning="send", tool_name="send_email", tool_args={"to": "a@example.com"}),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    run = AgentRun.objects.create(
        organization=organization,
        idempotency_key="run-1",
        goal="proactive acquisition",
        max_steps=10,
    )

    first = continue_agent_run(run=run, planner=planner, tools=tools)
    assert first.status == "waiting_approval"
    run.refresh_from_db()
    assert run.status == AgentRun.Status.WAITING_APPROVAL
    assert run.steps.count() == 2
    token = first.pending_approval.approval_token

    resumed = continue_agent_run(run=run, planner=planner, tools=tools, approvals={token})
    assert resumed.status == "completed"
    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.steps.count() == 3
    assert list(run.steps.order_by("index").values_list("index", flat=True)) == [0, 1, 2]
    assert list(run.steps.order_by("index").values_list("outcome", flat=True)) == [
        "succeeded",
        "blocked_approval",
        "succeeded",
    ]


def test_pipeline_grade_tool_drives_real_scoring():
    tools = ToolRegistry(build_pipeline_tools())
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="score",
                tool_name="grade_candidate",
                tool_args={
                    "primary_type": "gearbox repair",
                    "types": ["industrial_supplier", "gearbox_repair_shop"],
                    "website": "https://x.example",
                    "country": "VN",
                },
            ),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="score company", memory=Memory())

    assert result.status == "completed"
    assert result.steps[0].output["grade"] in {"A", "B", "C"}


def test_pipeline_judge_tool_is_org_scoped(organization):
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="PT Mitra",
        country="Vietnam",
        website="https://mitra.example",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
        record_hash="judge-agent-hash",
    )
    tools = ToolRegistry(build_pipeline_tools(organization=organization))
    planner = DeterministicPlanner(
        [
            Plan(reasoning="judge", tool_name="judge_candidate", tool_args={"candidate_id": str(candidate.id)}),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="judge", memory=Memory())

    assert result.status == "completed"
    assert result.steps[0].output["grade"] in {"A", "B", "C"}


def test_proactive_acquisition_runs_end_to_end_with_approval(organization):
    from apps.growth.agent.acquisition import run_proactive_acquisition

    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="PT Mitra",
        country="Vietnam",
        website="",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
        record_hash="proactive-agent-hash",
        is_demo=False,
    )

    first = run_proactive_acquisition(organization=organization, candidate_id=str(candidate.id))
    assert first.status == "waiting_approval"
    token = first.pending_approval.approval_token

    run = AgentRun.objects.get(organization=organization, idempotency_key=f"proactive:{candidate.id}")
    assert list(run.steps.order_by("index").values_list("outcome", flat=True)) == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "blocked_approval",
    ]

    resumed = run_proactive_acquisition(
        organization=organization,
        candidate_id=str(candidate.id),
        approvals={token},
    )
    assert resumed.status == "completed"
    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.steps.count() == 6

    account = TargetAccount.objects.get(
        organization=organization,
        source_identity=f"candidate:{candidate.id}",
    )
    follow_up = FollowUp.objects.get(organization=organization, account=account)
    assert follow_up.stage == "EMAIL_1_SENT"
    assert OutreachMessage.objects.filter(
        organization=organization,
        account=account,
        status=OutreachMessage.Status.SENT,
    ).count() == 1


def test_proactive_acquisition_day_delivers_review_queue_and_is_idempotent(organization):
    from apps.growth.agent.acquisition import run_proactive_acquisition_day

    candidates = []
    for index in range(3):
        candidates.append(
            DiscoveryCandidate.objects.create(
                organization=organization,
                company_name=f"Company {index}",
                country="Vietnam",
                website="",
                industry="gearbox repair",
                status=DiscoveryCandidate.Status.ACCEPTED,
                import_format="GOOGLE_MAPS",
                raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
                record_hash=f"day-hash-{index}",
                is_demo=False,
                score=70 - index,
            )
        )

    first = run_proactive_acquisition_day(organization=organization, limit=10)
    assert first["candidates"] == 3
    assert first["waiting_approval"] == 3
    assert len(first["pending_approvals"]) == 3

    tokens = {item["approval_token"] for item in first["pending_approvals"]}
    second = run_proactive_acquisition_day(organization=organization, limit=10, approvals=tokens)
    assert second["completed"] == 3
    assert second["waiting_approval"] == 0

    for candidate in candidates:
        run = AgentRun.objects.get(
            organization=organization,
            idempotency_key=f"proactive:{candidate.id}",
        )
        assert run.status == AgentRun.Status.COMPLETED
        assert run.steps.count() == 6


    third = run_proactive_acquisition_day(organization=organization, limit=10)
    assert third["completed"] == 3
    for candidate in candidates:
        run = AgentRun.objects.get(
            organization=organization,
            idempotency_key=f"proactive:{candidate.id}",
        )
        assert run.steps.count() == 6


def test_inbound_triage_tool_routes_lead(organization):
    from apps.growth.agent.inbound_tools import build_inbound_triage_tools
    from apps.growth.inbound_rfq import record_inbound_rfq

    result = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a replacement gear.",
        product_interest="gearbox",
    )
    tools = ToolRegistry(build_inbound_triage_tools(organization))
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="route lead",
                tool_name="triage_inbound_lead",
                tool_args={"lead_id": result["lead_id"]},
            ),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    run = runtime.run(goal="triage inbound", memory=Memory())

    assert run.status == "completed"
    assert run.steps[0].output["route"] == "ACQUISITION"
