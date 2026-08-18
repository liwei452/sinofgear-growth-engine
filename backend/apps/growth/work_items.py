from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q

from .email_delivery import email_delivery_readiness
from .models import (
    AgentRun,
    ChannelPackage,
    CustomerServiceTurn,
    GrowthMission,
    GrowthPublishItem,
    InboundLead,
    MissionEntityLink,
    MissionPlan,
)


@dataclass(frozen=True)
class WorkItemProjection:
    id: str
    mission_id: str | None
    mission_title: str
    kind: str
    title: str
    summary: str
    priority: str
    source_type: str
    source_id: str
    source_ids: tuple[str, ...]
    action_type: str
    action_label: str
    preview: dict
    created_at: datetime


_PRIORITY_ORDER = {"URGENT": 0, "HIGH": 1, "NORMAL": 2}


def _mission_identity(organization_id, entity_type, entity_id):
    link = MissionEntityLink.objects.filter(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
    ).select_related("mission").first()
    if link is None:
        return None, "未归属增长任务"
    return str(link.mission_id), link.mission.title


def _include(mission, mission_id):
    return mission is None or (mission_id is not None and str(mission.id) == mission_id)


def _project_agent_review(items, organization, mission):
    runs = AgentRun.objects.filter(
        organization=organization,
        status=AgentRun.Status.WAITING_APPROVAL,
    ).prefetch_related("steps")
    for run in runs:
        pending = next(
            (
                step
                for step in run.steps.all()
                if step.outcome == "blocked_approval"
            ),
            None,
        )
        if pending is None:
            continue
        mission_id, mission_title = _mission_identity(
            organization.id, MissionEntityLink.EntityType.AGENT_RUN, run.id
        )
        if not _include(mission, mission_id):
            continue
        is_send_email = pending.tool_name == "send_email"
        if is_send_email and email_delivery_readiness() != "CONNECTED":
            items.append(
                WorkItemProjection(
                    id=f"CONFIGURATION_BLOCK:{run.id}",
                    mission_id=mission_id,
                    mission_title=mission_title,
                    kind="CONFIGURATION_BLOCK",
                    title="等待管理员连接邮箱",
                    summary="邮件渠道尚未接通，开发信已生成但不能发送。",
                    priority="HIGH",
                    source_type="agent_run",
                    source_id=str(run.id),
                    source_ids=(str(run.id),),
                    action_type="OPEN_SETTINGS",
                    action_label="等待管理员连接邮箱",
                    preview={"draft": (pending.output or {}).get("english_draft", "")},
                    created_at=run.created_at,
                )
            )
            continue
        if is_send_email:
            items.append(
                WorkItemProjection(
                    id=f"OUTREACH_REVIEW:{run.id}",
                    mission_id=mission_id,
                    mission_title=mission_title,
                    kind="OUTREACH_REVIEW",
                    title="批准开发信",
                    summary="Agent 已生成个性化开发信，等待人工批准发送。",
                    priority="HIGH",
                    source_type="agent_run",
                    source_id=str(run.id),
                    source_ids=(str(run.id),),
                    action_type="APPROVE_AGENT_RUN",
                    action_label="批准并发送",
                    preview={"draft": (pending.output or {}).get("english_draft", "")},
                    created_at=run.created_at,
                )
            )
        else:
            items.append(
                WorkItemProjection(
                    id=f"AGENT_REVIEW:{run.id}",
                    mission_id=mission_id,
                    mission_title=mission_title,
                    kind="AGENT_REVIEW",
                    title="Agent 待审核",
                    summary="Agent 执行到需要人工判断的步骤。",
                    priority="NORMAL",
                    source_type="agent_run",
                    source_id=str(run.id),
                    source_ids=(str(run.id),),
                    action_type="APPROVE_AGENT_RUN",
                    action_label="批准",
                    preview={},
                    created_at=run.created_at,
                )
            )


def _project_social_review(items, organization, mission):
    packages = list(
        ChannelPackage.objects.filter(
            organization=organization,
            status="AWAITING_REVIEW",
            is_demo=False,
        ).select_related("source_platform_content")
    )
    groups: dict[str, list] = {}
    for package in packages:
        master_id = (
            str(package.source_platform_content.master_content_id)
            if package.source_platform_content
            else str(package.id)
        )
        groups.setdefault(master_id, []).append(package)
    for master_id, group in groups.items():
        source_ids = tuple(sorted(str(package.id) for package in group))
        mission_id, mission_title = _mission_identity(
            organization.id,
            MissionEntityLink.EntityType.CHANNEL_PACKAGE,
            group[0].id,
        )
        if not _include(mission, mission_id):
            continue
        items.append(
            WorkItemProjection(
                id=f"SOCIAL_REVIEW:{master_id}",
                mission_id=mission_id,
                mission_title=mission_title,
                kind="SOCIAL_REVIEW",
                title="批准社媒内容",
                summary="一组多平台社媒内容等待统一批准。",
                priority="HIGH",
                source_type="channel_package_group",
                source_id=source_ids[0],
                source_ids=source_ids,
                action_type="APPROVE_CHANNEL_PACKAGE_GROUP",
                action_label="批准并排期",
                preview={
                    "platforms": [
                        {
                            "channel": package.channel,
                            "title": (package.payload or {}).get("title", ""),
                        }
                        for package in group
                    ]
                },
                created_at=min(package.created_at for package in group),
            )
        )


def _project_publish_failures(items, organization, mission):
    failed = list(
        GrowthPublishItem.objects.filter(
            organization=organization,
            status=GrowthPublishItem.Status.FAILED,
            batch__is_demo=False,
        ).select_related("batch")
    )
    by_batch: dict[str, list] = {}
    for item in failed:
        by_batch.setdefault(str(item.batch_id), []).append(item)
    for batch_id, group in by_batch.items():
        mission_id, mission_title = _mission_identity(
            organization.id,
            MissionEntityLink.EntityType.PUBLISH_BATCH,
            group[0].batch_id,
        )
        if not _include(mission, mission_id):
            continue
        items.append(
            WorkItemProjection(
                id=f"EXECUTION_FAILURE:{batch_id}",
                mission_id=mission_id,
                mission_title=mission_title,
                kind="EXECUTION_FAILURE",
                title="发布失败",
                summary="部分平台发布失败，需要重试或人工处理。",
                priority="HIGH",
                source_type="publish_batch",
                source_id=batch_id,
                source_ids=tuple(str(item.id) for item in group),
                action_type="RETRY_PUBLISH_BATCH",
                action_label="重试失败渠道",
                preview={},
                created_at=min(item.created_at for item in group),
            )
        )


def _project_customer_replies(items, organization, mission):
    lead_ids = set(
        InboundLead.objects.filter(
            organization=organization,
            is_demo=False,
        )
        .filter(
            Q(route=InboundLead.Route.MANUAL_REVIEW)
            | Q(
                customer_service_turns__decision=CustomerServiceTurn.Decision.HUMAN_ESCALATION
            )
        )
        .values_list("id", flat=True)
    )
    leads = InboundLead.objects.filter(id__in=lead_ids).order_by("created_at", "id")
    for lead in leads:
        mission_id, mission_title = _lead_mission(organization.id, lead.id)
        if not _include(mission, mission_id):
            continue
        items.append(
            WorkItemProjection(
                id=f"CUSTOMER_REPLY:{lead.id}",
                mission_id=mission_id,
                mission_title=mission_title,
                kind="CUSTOMER_REPLY",
                title="客户回复待处理",
                summary="客户回复或升级需要人工处理。",
                priority="URGENT",
                source_type="inbound_lead",
                source_id=str(lead.id),
                source_ids=(str(lead.id),),
                action_type="OPEN_CUSTOMER",
                action_label="处理客户",
                preview={},
                created_at=lead.created_at,
            )
        )


def _lead_mission(organization_id, lead_id):
    lead = InboundLead.objects.filter(id=lead_id).first()
    if lead is None or lead.account_id is None:
        return None, "未归属增长任务"
    return _mission_identity(
        organization_id,
        MissionEntityLink.EntityType.TARGET_ACCOUNT,
        lead.account_id,
    )


def _project_configuration_blocks(items, organization, mission):
    running = GrowthMission.objects.filter(
        organization=organization,
        status=GrowthMission.Status.RUNNING,
    )
    for current in running:
        has_approved = MissionPlan.objects.filter(
            mission=current,
            status=MissionPlan.Status.APPROVED,
        ).exists()
        if has_approved:
            continue
        if not _include(mission, str(current.id)):
            continue
        items.append(
            WorkItemProjection(
                id=f"CONFIGURATION_BLOCK:{current.id}",
                mission_id=str(current.id),
                mission_title=current.title,
                kind="CONFIGURATION_BLOCK",
                title="缺少已批准的执行计划",
                summary="运行中的任务没有已批准的执行计划。",
                priority="HIGH",
                source_type="growth_mission",
                source_id=str(current.id),
                source_ids=(str(current.id),),
                action_type="OPEN_SETTINGS",
                action_label="前往配置",
                preview={},
                created_at=current.created_at,
            )
        )


def project_work_items(*, organization, mission=None) -> list[WorkItemProjection]:
    items: list[WorkItemProjection] = []
    _project_agent_review(items, organization, mission)
    _project_social_review(items, organization, mission)
    _project_publish_failures(items, organization, mission)
    _project_customer_replies(items, organization, mission)
    _project_configuration_blocks(items, organization, mission)

    deduped = {item.id: item for item in items}
    return sorted(
        deduped.values(),
        key=lambda item: (
            _PRIORITY_ORDER.get(item.priority, 3),
            item.created_at or datetime.min,
        ),
    )
