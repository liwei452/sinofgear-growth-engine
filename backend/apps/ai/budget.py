from __future__ import annotations

from datetime import UTC
from decimal import Decimal, InvalidOperation, ROUND_UP

from django.db import transaction
from django.utils import timezone

from apps.identity.models import Organization

from .models import AIProviderConfiguration, AIUsageAttempt, AIUsageDay


_MONEY_QUANTUM = Decimal("0.000001")
# Official DeepSeek pricing verified 2026-08-12. Provider prices can change;
# changing these values requires a new immutable version for audit replay.
PRICING_CODE = "deepseek-official-usd-2026-08-12"
PRICING_VERSION = 2
# USD / one million tokens. Reservation rates in routing.py are intentionally
# separate conservative ceilings and remain above these actual rates.
_PRICING = {
    "deepseek-v4-flash": {
        "input": Decimal("0.14"), "cache": Decimal("0.0028"), "output": Decimal("0.28"),
    },
    "deepseek-v4-pro": {
        "input": Decimal("0.435"), "cache": Decimal("0.003625"), "output": Decimal("0.87"),
    },
}


class BudgetExceeded(RuntimeError):
    pass


def _nonnegative_decimal(value, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value)).quantize(_MONEY_QUANTUM, rounding=ROUND_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a decimal amount.") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must not be negative.")
    return parsed


def _token_count(metadata, field):
    value = metadata.get(field, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer.")
    return value


def calculate_actual_cost(*, model: str, metadata: dict) -> Decimal:
    prices = _PRICING.get(model)
    if prices is None or not isinstance(metadata, dict):
        raise ValueError("Provider usage pricing is unavailable.")
    required = {"input_tokens", "output_tokens", "cache_hit_tokens"}
    if not required <= metadata.keys():
        raise ValueError("Provider usage counts are incomplete.")
    input_tokens = _token_count(metadata, "input_tokens")
    output_tokens = _token_count(metadata, "output_tokens")
    cache_tokens = _token_count(metadata, "cache_hit_tokens")
    if cache_tokens > input_tokens:
        raise ValueError("cache_hit_tokens cannot exceed input_tokens.")
    uncached = input_tokens - cache_tokens
    cost = (
        Decimal(uncached) * prices["input"]
        + Decimal(cache_tokens) * prices["cache"]
        + Decimal(output_tokens) * prices["output"]
    ) / Decimal(1_000_000)
    return cost.quantize(_MONEY_QUANTUM, rounding=ROUND_UP)


@transaction.atomic
def reserve_budget(intent, run) -> AIUsageAttempt:
    if run.organization_id != intent.organization_id or run.job_id != intent.job_id:
        raise ValueError("Usage run and execution intent must belong to the same job.")
    existing = AIUsageAttempt.objects.select_for_update().filter(run=run).first()
    if existing is not None:
        return existing
    # The organization lock provides one portable serialization point. The day
    # row lock below is the production PostgreSQL ledger lock.
    Organization.objects.select_for_update().get(pk=intent.organization_id)
    # A concurrent caller may have created the run reservation while this
    # transaction waited for the organization lock.
    existing = AIUsageAttempt.objects.select_for_update().filter(run=run).first()
    if existing is not None:
        return existing
    configuration = AIProviderConfiguration.objects.select_for_update().get(
        organization_id=intent.organization_id
    )
    if (
        configuration.connection_state
        != AIProviderConfiguration.ConnectionState.CONNECTED
        or configuration.operation_token is not None
        or configuration.operation_started_at is not None
    ):
        raise BudgetExceeded("deepseek_not_connected")
    # Organization-scoped ledger with an exact UTC boundary, independent of
    # process or presentation timezone.
    usage_date = timezone.now().astimezone(UTC).date()
    day, _ = AIUsageDay.objects.get_or_create(
        organization_id=intent.organization_id, usage_date=usage_date
    )
    day = AIUsageDay.objects.select_for_update().get(pk=day.pk)
    reservation = _nonnegative_decimal(
        intent.reserved_cost_usd, field="reserved_cost_usd"
    )
    if day.reserved_usd + day.actual_usd + reservation > configuration.daily_budget_usd:
        raise BudgetExceeded("deepseek_daily_budget_exceeded")
    attempt = AIUsageAttempt.objects.create(
        run=run,
        intent=intent,
        usage_day=day,
        status=AIUsageAttempt.Status.RESERVED,
        reserved_usd=reservation,
    )
    day.reserved_usd += reservation
    day.save(update_fields=["reserved_usd", "updated_at"])
    return attempt


@transaction.atomic
def reconcile_usage(attempt, metadata, status) -> None:
    if status not in {
        AIUsageAttempt.Status.SUCCEEDED,
        AIUsageAttempt.Status.FAILED,
        AIUsageAttempt.Status.CANCELED,
    }:
        raise ValueError("Usage reconciliation requires a terminal status.")
    locked = AIUsageAttempt.objects.select_for_update().get(pk=attempt.pk)
    if locked.reconciled_at is not None:
        return
    day = AIUsageDay.objects.select_for_update().get(pk=locked.usage_day_id)
    metadata = metadata if isinstance(metadata, dict) else {}
    if status == AIUsageAttempt.Status.CANCELED:
        actual = Decimal("0")
    elif status == AIUsageAttempt.Status.SUCCEEDED:
        actual = calculate_actual_cost(model=locked.intent.model, metadata=metadata)
    else:
        # A failed/ambiguous paid call keeps its conservative reservation as
        # actual usage unless the provider reports a lower known amount.
        actual = locked.reserved_usd
    input_tokens = _token_count(metadata, "input_tokens")
    output_tokens = _token_count(metadata, "output_tokens")
    cache_hit_tokens = _token_count(metadata, "cache_hit_tokens")
    day.reserved_usd -= locked.reserved_usd
    if day.reserved_usd < 0:
        raise ValueError("Usage ledger reservation cannot become negative.")
    day.actual_usd += actual
    day.save(update_fields=["reserved_usd", "actual_usd", "updated_at"])
    locked.status = status
    locked.actual_usd = actual
    locked.input_tokens = input_tokens
    locked.output_tokens = output_tokens
    locked.cache_hit_tokens = cache_hit_tokens
    locked.pricing_code = PRICING_CODE
    locked.pricing_version = PRICING_VERSION
    locked.reconciled_at = timezone.now()
    locked.save(
        update_fields=[
            "status", "actual_usd", "input_tokens", "output_tokens",
            "cache_hit_tokens", "pricing_code", "pricing_version", "reconciled_at",
        ]
    )
