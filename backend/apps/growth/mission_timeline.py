from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import AgentRunStep, GrowthMission, MissionEntityLink, MissionPlan


_CONTENT_ENTITY_LABELS = {
    MissionEntityLink.EntityType.CAMPAIGN: ("CAMPAIGN", "Campaign"),
    MissionEntityLink.EntityType.CONTENT_BRIEF: ("BRIEF", "Content brief"),
    MissionEntityLink.EntityType.MASTER_CONTENT: ("MASTER", "Master content"),
    MissionEntityLink.EntityType.PLATFORM_CONTENT: ("PLATFORM", "Platform content"),
    MissionEntityLink.EntityType.CHANNEL_PACKAGE: ("PACKAGE", "Channel package"),
    MissionEntityLink.EntityType.PUBLISH_BATCH: ("BATCH", "Publish batch"),
}


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

    for link in MissionEntityLink.objects.filter(
        mission=mission,
        entity_type__in=_CONTENT_ENTITY_LABELS,
    ).order_by("created_at", "id"):
        state, label = _CONTENT_ENTITY_LABELS[link.entity_type]
        items.append(
            MissionTimelineItem(
                occurred_at=link.created_at,
                lane=link.lane,
                state=state,
                title=label,
                summary="",
                evidence_type=link.entity_type,
                evidence_id=str(link.entity_id),
            )
        )

    return sorted(items, key=lambda item: item.occurred_at)
