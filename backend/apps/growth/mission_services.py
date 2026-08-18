from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count

from apps.campaigns.models import Campaign, ContentBrief
from apps.content.models import MasterContent, PlatformContent

from .models import (
    AgentRun,
    ChannelPackage,
    DiscoveryCandidate,
    DiscoveryRun,
    GrowthMission,
    GrowthPublishBatch,
    InboundRfq,
    MetricReceipt,
    MissionEntityLink,
    MissionPlan,
    OutreachDraft,
    OutreachMessage,
    SalesDeal,
    TargetAccount,
)


_TERMINAL = {GrowthMission.Status.COMPLETED, GrowthMission.Status.TERMINATED}


def _apply_values(mission: GrowthMission, values: dict) -> None:
    field_names = {
        "title",
        "objective",
        "target_countries",
        "target_industries",
        "customer_profile",
        "primary_product_id",
        "start_date",
        "end_date",
        "target_account_count",
        "target_reply_count",
        "target_rfq_count",
        "budget_micros",
        "allowed_channels",
    }
    for field in field_names:
        if field in values:
            setattr(mission, field, values[field])


@transaction.atomic
def create_mission(*, organization, actor, values: dict) -> GrowthMission:
    mission_id = uuid.uuid4()
    mission = GrowthMission(
        organization=organization,
        created_by=actor,
        id=mission_id,
        attribution_code=f"gm-{mission_id.hex[:12]}",
    )
    _apply_values(mission, values)
    mission.full_clean()
    mission.save()
    return mission


@transaction.atomic
def update_draft_mission(*, mission: GrowthMission, actor, values: dict) -> GrowthMission:
    del actor
    locked = GrowthMission.objects.select_for_update().get(pk=mission.pk)
    if locked.status != GrowthMission.Status.DRAFT:
        raise ValidationError("Only draft missions can be edited.")
    _apply_values(locked, values)
    locked.full_clean()
    locked.save()
    return locked


@transaction.atomic
def transition_mission(
    *, mission: GrowthMission, actor, target_status: str, reason: str = ""
) -> GrowthMission:
    del actor
    locked = GrowthMission.objects.select_for_update().get(pk=mission.pk)
    current = locked.status
    target = target_status

    allowed = {
        (GrowthMission.Status.DRAFT, GrowthMission.Status.PENDING_APPROVAL),
        (GrowthMission.Status.RUNNING, GrowthMission.Status.PAUSED),
        (GrowthMission.Status.PAUSED, GrowthMission.Status.RUNNING),
    }
    if target == GrowthMission.Status.TERMINATED:
        if current in _TERMINAL:
            raise ValidationError("A terminal mission cannot be terminated again.")
    elif target == GrowthMission.Status.COMPLETED:
        if not locked.plans.filter(status=MissionPlan.Status.APPROVED).exists():
            raise ValidationError("Mission cannot complete without an approved plan.")
    elif (current, target) not in allowed:
        raise ValidationError(f"Cannot transition mission from {current} to {target}.")

    locked.status = target
    if reason and target in {GrowthMission.Status.TERMINATED, GrowthMission.Status.COMPLETED}:
        locked.health_reason = reason
        locked.save(update_fields=["status", "health_reason", "updated_at"])
    else:
        locked.save(update_fields=["status", "updated_at"])
    return locked


def mission_available_actions(mission: GrowthMission, *, can_manage: bool, can_review: bool) -> list[str]:
    actions: list[str] = []
    if not can_manage and not can_review:
        return actions
    if can_manage:
        if mission.status == GrowthMission.Status.DRAFT:
            actions.extend(["edit", "generate_plan", "terminate"])
        elif mission.status == GrowthMission.Status.PENDING_APPROVAL:
            actions.extend(["generate_plan", "terminate"])
        elif mission.status == GrowthMission.Status.RUNNING:
            actions.extend(["pause", "terminate"])
        elif mission.status == GrowthMission.Status.PAUSED:
            actions.extend(["resume", "terminate"])
    if can_review and mission.status == GrowthMission.Status.PENDING_APPROVAL:
        actions.append("approve_plan")
    return actions


def mission_lane_counts(mission: GrowthMission) -> dict[str, int]:
    counts = {lane: 0 for lane in MissionEntityLink.Lane.values}
    rows = (
        MissionEntityLink.objects.filter(mission=mission)
        .values("lane")
        .annotate(total=Count("id"))
    )
    for row in rows:
        counts[row["lane"]] = row["total"]
    return counts


def _entity_type_for(entity) -> str:
    registry = (
        (TargetAccount, MissionEntityLink.EntityType.TARGET_ACCOUNT),
        (DiscoveryCandidate, MissionEntityLink.EntityType.DISCOVERY_CANDIDATE),
        (DiscoveryRun, MissionEntityLink.EntityType.DISCOVERY_RUN),
        (AgentRun, MissionEntityLink.EntityType.AGENT_RUN),
        (OutreachDraft, MissionEntityLink.EntityType.OUTREACH_DRAFT),
        (OutreachMessage, MissionEntityLink.EntityType.OUTREACH_MESSAGE),
        (Campaign, MissionEntityLink.EntityType.CAMPAIGN),
        (ContentBrief, MissionEntityLink.EntityType.CONTENT_BRIEF),
        (MasterContent, MissionEntityLink.EntityType.MASTER_CONTENT),
        (PlatformContent, MissionEntityLink.EntityType.PLATFORM_CONTENT),
        (ChannelPackage, MissionEntityLink.EntityType.CHANNEL_PACKAGE),
        (GrowthPublishBatch, MissionEntityLink.EntityType.PUBLISH_BATCH),
        (MetricReceipt, MissionEntityLink.EntityType.METRIC_RECEIPT),
        (InboundRfq, MissionEntityLink.EntityType.INBOUND_RFQ),
        (SalesDeal, MissionEntityLink.EntityType.SALES_DEAL),
    )
    for model, entity_type in registry:
        if isinstance(entity, model):
            return entity_type
    raise ValidationError("Unsupported mission entity type.")


def link_mission_entity(*, mission, entity, lane, actor=None) -> MissionEntityLink:
    if entity.organization_id != mission.organization_id:
        raise ValidationError("Entity organization must match the mission organization.")
    entity_type = _entity_type_for(entity)
    link, _ = MissionEntityLink.objects.get_or_create(
        organization=mission.organization,
        mission=mission,
        entity_type=entity_type,
        entity_id=entity.id,
        defaults={"lane": lane, "linked_by": actor},
    )
    return link


_STEP_LINK_MAP = (
    ("account_id", TargetAccount, MissionEntityLink.Lane.ACQUISITION),
    ("candidate_id", DiscoveryCandidate, MissionEntityLink.Lane.ACQUISITION),
    ("draft_id", OutreachDraft, MissionEntityLink.Lane.OUTREACH),
    ("message_id", OutreachMessage, MissionEntityLink.Lane.OUTREACH),
    ("campaign_id", Campaign, MissionEntityLink.Lane.SOCIAL),
    ("brief_id", ContentBrief, MissionEntityLink.Lane.SOCIAL),
    ("master_content_id", MasterContent, MissionEntityLink.Lane.SOCIAL),
    ("platform_content_id", PlatformContent, MissionEntityLink.Lane.SOCIAL),
    ("package_id", ChannelPackage, MissionEntityLink.Lane.SOCIAL),
    ("batch_id", GrowthPublishBatch, MissionEntityLink.Lane.SOCIAL),
    ("rfq_id", InboundRfq, MissionEntityLink.Lane.ATTRIBUTION),
)


def sync_mission_links_from_agent_run(*, run, actor=None):
    link = MissionEntityLink.objects.filter(
        mission__organization=run.organization,
        entity_type=MissionEntityLink.EntityType.AGENT_RUN,
        entity_id=run.id,
    ).first()
    if link is None:
        return
    mission = link.mission
    for step in run.steps.filter(outcome="succeeded"):
        output = step.output or {}
        for key, model, lane in _STEP_LINK_MAP:
            raw_id = output.get(key)
            if not raw_id:
                continue
            try:
                entity = model.objects.get(organization=run.organization, id=raw_id)
            except model.DoesNotExist:
                continue
            link_mission_entity(mission=mission, entity=entity, lane=lane, actor=actor)
