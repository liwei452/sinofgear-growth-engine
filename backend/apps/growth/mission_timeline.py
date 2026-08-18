from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import AgentRunStep, GrowthMission, MissionEntityLink, MissionPlan


@dataclass(frozen=True)
class MissionTimelineItem:
    occurred_at: datetime
    lane: str
    state: str
    title: str
    summary: str
    evidence_type: str
    evidence_id: str


def project_mission_timeline(*, mission: GrowthMission) -> list[MissionTimelineItem]:
    items: list[MissionTimelineItem] = []

    run_ids = list(
        MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=MissionEntityLink.EntityType.AGENT_RUN,
        ).values_list("entity_id", flat=True)
    )
    for step in (
        AgentRunStep.objects.filter(run_id__in=run_ids)
        .select_related("run")
        .order_by("created_at", "id")
    ):
        lane = "SOCIAL" if step.run.agent_type != "proactive" else "OUTREACH"
        items.append(
            MissionTimelineItem(
                occurred_at=step.created_at,
                lane=lane,
                state=step.outcome,
                title=step.tool_name or "agent step",
                summary=step.reasoning or step.error or "",
                evidence_type="agent_run_step",
                evidence_id=str(step.id),
            )
        )

    for plan in mission.plans.filter(status=MissionPlan.Status.APPROVED):
        items.append(
            MissionTimelineItem(
                occurred_at=plan.approved_at or plan.created_at,
                lane="ATTRIBUTION",
                state="APPROVED",
                title="执行计划已批准",
                summary=f"Plan v{plan.version} approved.",
                evidence_type="mission_plan",
                evidence_id=str(plan.id),
            )
        )

    return sorted(items, key=lambda item: item.occurred_at)
