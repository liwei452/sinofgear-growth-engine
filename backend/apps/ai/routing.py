from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.identity.permissions import PermissionCode
from apps.jobs.models import Job

from .models import AIExecutionIntent, AIProviderConfiguration


POLICY_CODE = "deepseek-routing-v1"
POLICY_VERSION = 1
_FLASH_MODEL = "deepseek-v4-flash"
_PRO_MODEL = "deepseek-v4-pro"
# Conservative reservation prices per million tokens. They are policy values,
# not provider-reported actual charges; reconciliation records actual metadata.
_INPUT_USD_PER_MILLION = { _FLASH_MODEL: Decimal("0.50"), _PRO_MODEL: Decimal("2.00") }
_OUTPUT_USD_PER_MILLION = { _FLASH_MODEL: Decimal("2.00"), _PRO_MODEL: Decimal("8.00") }
_MONEY_QUANTUM = Decimal("0.000001")
MAX_PROVIDER_INPUT_BYTES = 1_000_000
ROUTING_SNAPSHOT_FIELDS = frozenset(
    {
        "provider", "model", "thinking_enabled", "policy_code", "policy_version",
        "override_reason", "max_output_tokens", "timeout_seconds",
    }
)


class InputBudgetExceeded(ValueError):
    pass


@dataclass(frozen=True)
class ProviderInputBudget:
    utf8_bytes: int


def build_provider_input(*, prompt: str, schema: dict, snapshot: dict) -> ProviderInputBudget:
    """Measure every bounded component that will be sent to the provider."""
    if not isinstance(prompt, str) or not isinstance(schema, dict) or not isinstance(snapshot, dict):
        raise InputBudgetExceeded("Provider input components are invalid.")
    schema_text = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_text = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    # The transport includes the schema in its system message. Snapshot is
    # measured independently as a conservative bound even when already rendered.
    size = sum(len(value.encode("utf-8")) for value in (prompt, schema_text, snapshot_text))
    if size > MAX_PROVIDER_INPUT_BYTES:
        raise InputBudgetExceeded("Provider input exceeds the size limit.")
    return ProviderInputBudget(utf8_bytes=max(1, size))


@dataclass(frozen=True)
class RoutingDecision:
    organization_id: object
    provider: str
    model: str
    thinking_enabled: bool
    policy_code: str
    policy_version: int
    override_reason: str
    max_output_tokens: int
    timeout_seconds: int
    estimated_input_tokens: int
    reserved_cost_usd: Decimal


def _organization_id(snapshot):
    if not isinstance(snapshot, dict):
        raise ValidationError("AI routing requires an object snapshot.")
    value = snapshot.get("organization_id")
    if not value:
        raise ValidationError("AI routing requires an organization snapshot.")
    return value


def _can_override(*, actor) -> bool:
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    from apps.identity.models import Membership
    from apps.identity.services import get_active_membership

    try:
        membership = get_active_membership(user=actor)
    except Membership.DoesNotExist:
        return False
    return PermissionCode.CREDENTIALS_MANAGE in membership.role.permissions


def _is_complex_lead(snapshot: dict) -> bool:
    signals = snapshot.get("routing_signals")
    if (
        isinstance(signals, dict)
        and signals.get("policy_version") == 1
        and any(
            code in {"CONFLICTING_QUANTITIES", "LOW_TRUSTED_CONFIDENCE", "DOMAIN_AMBIGUITY"}
            for code in signals.get("codes", [])
        )
    ):
        return True
    return False


def _estimated_tokens(snapshot: dict) -> int:
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    # One token per byte deliberately over-reserves rather than under-counting.
    return max(1, len(encoded))


def _reserved_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    cost = (
        Decimal(input_tokens) * _INPUT_USD_PER_MILLION[model]
        + Decimal(output_tokens) * _OUTPUT_USD_PER_MILLION[model]
    ) / Decimal(1_000_000)
    return cost.quantize(_MONEY_QUANTUM, rounding=ROUND_UP)


def route_ai_work(
    *, job_type, snapshot, administrator_override=False, actor=None,
    provider_input=None,
) -> RoutingDecision:
    organization_id = _organization_id(snapshot)
    try:
        configuration = AIProviderConfiguration.objects.get(
            organization_id=organization_id
        )
    except (AIProviderConfiguration.DoesNotExist, ValueError):
        raise ValidationError("deepseek_not_connected") from None
    if (
        configuration.connection_state
        != AIProviderConfiguration.ConnectionState.CONNECTED
        or configuration.operation_token is not None
        or configuration.operation_started_at is not None
    ):
        raise ValidationError("deepseek_not_connected")
    if administrator_override and not _can_override(actor=actor):
        raise PermissionDenied("credentials.manage is required for enhanced analysis.")
    complex_route = administrator_override or (
        job_type == Job.Type.LEAD_ANALYZE and _is_complex_lead(snapshot)
    )
    model = _PRO_MODEL if complex_route else _FLASH_MODEL
    max_output_tokens = (
        configuration.pro_max_output_tokens
        if complex_route else configuration.flash_max_output_tokens
    )
    estimated_input_tokens = (
        provider_input.utf8_bytes
        if isinstance(provider_input, ProviderInputBudget)
        else _estimated_tokens(snapshot)
    )
    return RoutingDecision(
        organization_id=configuration.organization_id,
        provider="deepseek",
        model=model,
        thinking_enabled=complex_route,
        policy_code=POLICY_CODE,
        policy_version=POLICY_VERSION,
        override_reason=(
            "administrator_enhanced_analysis" if administrator_override else ""
        ),
        max_output_tokens=max_output_tokens,
        timeout_seconds=configuration.timeout_seconds,
        estimated_input_tokens=estimated_input_tokens,
        reserved_cost_usd=_reserved_cost(
            model, estimated_input_tokens, max_output_tokens
        ),
    )


@transaction.atomic
def create_execution_intent(*, job, decision, created_by=None) -> AIExecutionIntent:
    locked_job = Job.objects.select_for_update().get(pk=job.pk)
    existing = AIExecutionIntent.objects.filter(job=locked_job).first()
    if existing is not None:
        return existing
    if str(locked_job.organization_id) != str(decision.organization_id):
        raise ValidationError("Routing decision organization does not match the job.")
    return AIExecutionIntent.objects.create(
        job=locked_job,
        organization_id=decision.organization_id,
        provider=decision.provider,
        model=decision.model,
        thinking_enabled=decision.thinking_enabled,
        policy_code=decision.policy_code,
        policy_version=decision.policy_version,
        override_reason=decision.override_reason,
        max_output_tokens=decision.max_output_tokens,
        timeout_seconds=decision.timeout_seconds,
        estimated_input_tokens=decision.estimated_input_tokens,
        reserved_cost_usd=decision.reserved_cost_usd,
        created_by=created_by,
    )


def routing_snapshot(decision: RoutingDecision) -> dict[str, object]:
    """Return the safe immutable routing fields suitable for a Job snapshot."""
    return {
        "provider": decision.provider,
        "model": decision.model,
        "thinking_enabled": decision.thinking_enabled,
        "policy_code": decision.policy_code,
        "policy_version": decision.policy_version,
        "override_reason": decision.override_reason,
        "max_output_tokens": decision.max_output_tokens,
        "timeout_seconds": decision.timeout_seconds,
    }


def validate_routing_snapshot(value, *, intent=None) -> bool:
    if not isinstance(value, dict) or set(value) != ROUTING_SNAPSHOT_FIELDS:
        return False
    if (
        value.get("provider") != "deepseek"
        or value.get("model") not in {_FLASH_MODEL, _PRO_MODEL}
        or not isinstance(value.get("thinking_enabled"), bool)
        or value.get("thinking_enabled") != (value.get("model") == _PRO_MODEL)
        or value.get("policy_code") != POLICY_CODE
        or value.get("policy_version") != POLICY_VERSION
        or value.get("override_reason") not in {"", "administrator_enhanced_analysis"}
        or not isinstance(value.get("max_output_tokens"), int)
        or isinstance(value.get("max_output_tokens"), bool)
        or value.get("max_output_tokens") <= 0
        or not isinstance(value.get("timeout_seconds"), int)
        or isinstance(value.get("timeout_seconds"), bool)
        or value.get("timeout_seconds") <= 0
    ):
        return False
    if intent is None:
        return True
    return value == routing_snapshot(
        RoutingDecision(
            organization_id=intent.organization_id,
            provider=intent.provider,
            model=intent.model,
            thinking_enabled=intent.thinking_enabled,
            policy_code=intent.policy_code,
            policy_version=intent.policy_version,
            override_reason=intent.override_reason,
            max_output_tokens=intent.max_output_tokens,
            timeout_seconds=intent.timeout_seconds,
            estimated_input_tokens=intent.estimated_input_tokens,
            reserved_cost_usd=intent.reserved_cost_usd,
        )
    )
