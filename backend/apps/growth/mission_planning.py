from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from jsonschema import Draft202012Validator

from apps.ai.provider_config import resolve_product_ai
from apps.ai.services import BudgetedAIProvider, reserve_ai_budget, settle_ai_budget

from .models import GrowthMission, MissionPlan


class MissionPlanGenerationError(RuntimeError):
    pass


MISSION_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "customer_development", "social_growth", "attribution", "risks"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "customer_development": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "daily_discovery_volume",
                "qualification_evidence",
                "outreach_angle",
                "approval_policy",
                "stop_conditions",
            ],
            "properties": {
                "daily_discovery_volume": {"type": "integer", "minimum": 1, "maximum": 500},
                "qualification_evidence": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1, "maxLength": 300},
                },
                "outreach_angle": {"type": "string", "minLength": 1, "maxLength": 1000},
                "approval_policy": {"const": "EVERY_EMAIL"},
                "stop_conditions": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": ["REPLIED", "UNSUBSCRIBED", "HARD_BOUNCE"]},
                },
            },
        },
        "social_growth": {
            "type": "object",
            "additionalProperties": False,
            "required": ["channels", "weekly_cadence", "content_themes", "approval_policy"],
            "properties": {
                "channels": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string"},
                },
                "weekly_cadence": {"type": "integer", "minimum": 1, "maximum": 35},
                "content_themes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "items": {"type": "string", "minLength": 1, "maxLength": 500},
                },
                "approval_policy": {"const": "CONTENT_GROUP"},
            },
        },
        "attribution": {
            "type": "object",
            "additionalProperties": False,
            "required": ["attribution_code", "utm_campaign", "confidence_labels"],
            "properties": {
                "attribution_code": {"type": "string", "minLength": 1, "maxLength": 64},
                "utm_campaign": {"type": "string", "minLength": 1, "maxLength": 128},
                "confidence_labels": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"enum": ["CONFIRMED", "ASSISTED", "UNATTRIBUTED"]},
                },
            },
        },
        "risks": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    },
}


def _deterministic_plan(mission: GrowthMission) -> dict:
    countries = mission.target_countries or ["GLOBAL"]
    industries = mission.target_industries or ["industrial equipment"]
    social_channels = [
        channel for channel in (mission.allowed_channels or []) if channel != "EMAIL"
    ] or ["LINKEDIN"]
    product_name = (
        mission.primary_product.name_en if mission.primary_product_id else "our product"
    )
    attribution_code = mission.attribution_code or f"gm-{mission.id.hex[:12]}"
    return {
        "summary": (
            f"Develop {', '.join(countries)} {', '.join(industries)} customers "
            f"for {product_name}."
        ),
        "customer_development": {
            "daily_discovery_volume": 20,
            "qualification_evidence": [
                f"Company serves {', '.join(industries)}",
                f"Primary product: {product_name}",
            ],
            "outreach_angle": (
                f"Reliable {product_name} supply for {', '.join(industries)} manufacturers."
            ),
            "approval_policy": "EVERY_EMAIL",
            "stop_conditions": ["REPLIED", "UNSUBSCRIBED", "HARD_BOUNCE"],
        },
        "social_growth": {
            "channels": social_channels,
            "weekly_cadence": 3,
            "content_themes": [
                f"Applications of {product_name} in {', '.join(industries)}"
            ],
            "approval_policy": "CONTENT_GROUP",
        },
        "attribution": {
            "attribution_code": attribution_code,
            "utm_campaign": f"gm-{attribution_code}",
            "confidence_labels": ["CONFIRMED", "ASSISTED", "UNATTRIBUTED"],
        },
        "risks": ["Target market and contact data must be verified before outreach."],
    }


def _mission_prompt(mission: GrowthMission) -> str:
    product_name = getattr(mission.primary_product, "name_en", "") or ""
    return (
        f"Create a growth execution plan for mission '{mission.title}'.\n"
        f"Objective: {mission.objective}\n"
        f"Primary product: {product_name}\n"
        f"Target countries: {', '.join(mission.target_countries or [])}\n"
        f"Target industries: {', '.join(mission.target_industries or [])}\n"
        f"Allowed channels: {', '.join(mission.allowed_channels or [])}\n"
        f"Attribution code: {mission.attribution_code}"
    )


def _validate_mission_plan_semantics(mission: GrowthMission, snapshot: dict) -> None:
    allowed_social = {
        channel for channel in (mission.allowed_channels or []) if channel != "EMAIL"
    }
    channels = set(snapshot.get("social_growth", {}).get("channels", []))
    if channels and allowed_social and not channels.issubset(allowed_social):
        raise MissionPlanGenerationError("Plan channels are outside the mission's allowed channels.")
    attribution_code = snapshot.get("attribution", {}).get("attribution_code", "")
    if mission.attribution_code and attribution_code != mission.attribution_code:
        raise MissionPlanGenerationError("Plan attribution code does not match the mission.")


@transaction.atomic
def generate_mission_plan(*, mission: GrowthMission, actor) -> MissionPlan:
    locked_mission = GrowthMission.objects.select_for_update().get(pk=mission.pk)
    version = (
        MissionPlan.objects.select_for_update()
        .filter(mission=locked_mission)
        .aggregate(max_version=Max("version"))["max_version"]
        or 0
    ) + 1

    runtime = resolve_product_ai(locked_mission.organization)
    if not runtime.real_requests_enabled:
        snapshot = _deterministic_plan(locked_mission)
        generation_mode = MissionPlan.GenerationMode.AUTOMATION
        provider = ""
        model = ""
    else:
        reserve_ai_budget(locked_mission.organization)
        try:
            budgeted = BudgetedAIProvider(
                organization=locked_mission.organization,
                model=runtime.model,
                provider=runtime.provider,
            )
            snapshot = budgeted.generate(
                prompt=_mission_prompt(locked_mission),
                schema=MISSION_PLAN_SCHEMA,
            )
            Draft202012Validator(MISSION_PLAN_SCHEMA).validate(snapshot)
        except MissionPlanGenerationError:
            raise
        except Exception as exc:
            raise MissionPlanGenerationError(
                "AI mission plan generation failed."
            ) from exc
        finally:
            settle_ai_budget(locked_mission.organization)
        generation_mode = MissionPlan.GenerationMode.AI_GENERATION
        provider = runtime.provider_code
        model = runtime.model

    _validate_mission_plan_semantics(locked_mission, snapshot)

    plan = MissionPlan.objects.create(
        organization=locked_mission.organization,
        mission=locked_mission,
        version=version,
        snapshot=snapshot,
        generation_mode=generation_mode,
        provider=provider,
        model=model,
        created_by=actor,
    )
    if locked_mission.status == GrowthMission.Status.DRAFT:
        locked_mission.status = GrowthMission.Status.PENDING_APPROVAL
        locked_mission.save(update_fields=["status", "updated_at"])
    return plan


@transaction.atomic
def approve_mission_plan(*, mission: GrowthMission, plan: MissionPlan, actor) -> MissionPlan:
    locked_mission = GrowthMission.objects.select_for_update().get(pk=mission.pk)
    locked_plan = MissionPlan.objects.select_for_update().get(pk=plan.pk)
    if locked_plan.mission_id != locked_mission.id:
        raise ValidationError("Plan does not belong to the mission.")
    if locked_plan.organization_id != locked_mission.organization_id:
        raise ValidationError("Plan organization does not match the mission.")
    if locked_mission.status != GrowthMission.Status.PENDING_APPROVAL:
        raise ValidationError("Mission must be pending approval before its plan is approved.")

    MissionPlan.objects.filter(mission=locked_mission).exclude(pk=locked_plan.pk).update(
        status=MissionPlan.Status.SUPERSEDED,
        updated_at=timezone.now(),
    )
    locked_plan.status = MissionPlan.Status.APPROVED
    locked_plan.approved_by = actor
    locked_plan.approved_at = timezone.now()
    locked_plan.save(
        update_fields=["status", "approved_by", "approved_at", "updated_at"]
    )
    locked_mission.status = GrowthMission.Status.RUNNING
    locked_mission.save(update_fields=["status", "updated_at"])
    return locked_plan
