from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count

from .models import GrowthMission, MissionEntityLink, MissionPlan


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
