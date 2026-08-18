import json
from decimal import Decimal, ROUND_CEILING

from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator

from apps.common.security import scrub_secrets
from apps.identity.models import Organization

from .models import AIRun, OrganizationAIProviderConfig, PromptVersion, ai_audit_writes
from .provider_config import DEEPSEEK_USD_PER_MILLION


class AIBudgetExceeded(RuntimeError):
    pass


AI_CALL_RESERVATION_TOKENS = 4000
AI_PLANNER_OUTPUT_TOKEN_ESTIMATE = 512


class BudgetedAIProvider:
    def __init__(self, *, organization, model: str, provider):
        self._organization = organization
        self._model = model
        self._provider = provider

    def generate(self, *, prompt: str, schema: dict) -> dict:
        input_estimate = max(1, (len(prompt) + 3) // 4)
        reserved_micros = reserve_ai_cost(
            self._organization,
            model=self._model,
            input_tokens=input_estimate,
            output_tokens=AI_PLANNER_OUTPUT_TOKEN_ESTIMATE,
        )
        try:
            return self._provider.generate(prompt=prompt, schema=schema)
        finally:
            settle_ai_cost(
                self._organization,
                reserved_micros=reserved_micros,
                model=self._model,
                usage=getattr(self._provider, "last_usage", None),
            )


def estimate_deepseek_cost_micros(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
) -> int:
    prices = DEEPSEEK_USD_PER_MILLION.get(model)
    if prices is None:
        raise ValueError("Unsupported DeepSeek model for cost estimation.")
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token estimates must not be negative.")
    microdollars = (
        Decimal(str(prices["input"])) * input_tokens
        + Decimal(str(prices["output"])) * output_tokens
    )
    return int(microdollars.to_integral_value(rounding=ROUND_CEILING))


def _reset_cost_day(config: OrganizationAIProviderConfig, today) -> None:
    if config.spent_on != today:
        config.spent_on = today
        config.daily_spent_micros = 0
        config.daily_reserved_micros = 0


@transaction.atomic
def reserve_ai_cost(
    organization,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    config = OrganizationAIProviderConfig.objects.select_for_update().filter(
        organization=organization
    ).first()
    if not config or not config.daily_budget_micros:
        return 0
    estimate = estimate_deepseek_cost_micros(
        model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    _reset_cost_day(config, timezone.now().date())
    if (
        config.daily_spent_micros
        + config.daily_reserved_micros
        + estimate
        > config.daily_budget_micros
    ):
        raise AIBudgetExceeded(
            "Organization daily estimated AI cost budget would be exceeded."
        )
    config.daily_reserved_micros += estimate
    config.save(update_fields=[
        "daily_spent_micros", "daily_reserved_micros", "spent_on", "updated_at",
    ])
    return estimate


@transaction.atomic
def settle_ai_cost(
    organization,
    *,
    reserved_micros: int,
    model: str,
    usage: dict | None = None,
    charge_on_unknown: bool = True,
) -> int:
    if reserved_micros <= 0:
        return 0
    config = OrganizationAIProviderConfig.objects.select_for_update().filter(
        organization=organization
    ).first()
    if not config:
        return 0
    _reset_cost_day(config, timezone.now().date())
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    if (
        isinstance(prompt_tokens, int)
        and prompt_tokens >= 0
        and isinstance(completion_tokens, int)
        and completion_tokens >= 0
    ):
        actual = estimate_deepseek_cost_micros(
            model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )
    else:
        actual = reserved_micros if charge_on_unknown else 0
    config.daily_reserved_micros = max(
        0, config.daily_reserved_micros - reserved_micros
    )
    config.daily_spent_micros += actual
    config.save(update_fields=[
        "daily_spent_micros", "daily_reserved_micros", "spent_on", "updated_at",
    ])
    return actual


def organization_daily_token_usage(organization_id, *, now=None) -> int:
    now = now or timezone.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    runs = AIRun.objects.filter(
        organization_id=organization_id,
        started_at__gte=start,
        status__in=[AIRun.Status.SUCCEEDED, AIRun.Status.FAILED],
    )
    for run in runs:
        metadata = run.provider_metadata
        if not isinstance(metadata, dict):
            continue
        usage = metadata.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("total_tokens"), int):
            total += usage["total_tokens"]
    return total


def assert_ai_budget_available(organization) -> None:
    budget = getattr(organization, "ai_daily_token_budget", None)
    if not budget:
        return
    used = organization_daily_token_usage(organization.id)
    if used >= budget:
        raise AIBudgetExceeded(
            f"Organization daily AI token budget exceeded ({used} >= {budget})."
        )


@transaction.atomic
def reserve_ai_budget(organization, tokens: int = AI_CALL_RESERVATION_TOKENS) -> None:
    locked = Organization.objects.select_for_update().get(pk=organization.id)
    budget = locked.ai_daily_token_budget
    if not budget:
        return
    today = timezone.now().date()
    if locked.ai_daily_reserved_on != today:
        locked.ai_daily_reserved_on = today
        locked.ai_daily_reserved_tokens = 0
    used = organization_daily_token_usage(locked.id)
    if used + locked.ai_daily_reserved_tokens + tokens > budget:
        raise AIBudgetExceeded(
            "Organization daily AI token budget exceeded by concurrent requests."
        )
    locked.ai_daily_reserved_tokens += tokens
    locked.save(update_fields=["ai_daily_reserved_tokens", "ai_daily_reserved_on", "updated_at"])


@transaction.atomic
def settle_ai_budget(organization, tokens: int = AI_CALL_RESERVATION_TOKENS) -> None:
    locked = Organization.objects.select_for_update().get(pk=organization.id)
    if not locked.ai_daily_token_budget:
        return
    locked.ai_daily_reserved_tokens = max(0, locked.ai_daily_reserved_tokens - tokens)
    locked.save(update_fields=["ai_daily_reserved_tokens", "updated_at"])


class PromptVersionService:
    @staticmethod
    @transaction.atomic
    def create(
        *, purpose, code, provider, model, template, output_schema,
        status=PromptVersion.Status.DRAFT, version=None, created_by=None,
    ) -> PromptVersion:
        Draft202012Validator.check_schema(output_schema)
        if version is None:
            latest = (
                PromptVersion.objects.select_for_update()
                .filter(purpose=purpose)
                .order_by("-version")
                .first()
            )
            version = 1 if latest is None else latest.version + 1
        with ai_audit_writes():
            return PromptVersion.objects.create(
                purpose=purpose,
                code=code,
                provider=provider,
                model=model,
                template=template,
                output_schema=json.loads(json.dumps(output_schema)),
                version=version,
                status=status,
                created_by=created_by,
            )


__all__ = [
    "AIBudgetExceeded",
    "BudgetedAIProvider",
    "PromptVersionService",
    "assert_ai_budget_available",
    "estimate_deepseek_cost_micros",
    "organization_daily_token_usage",
    "reserve_ai_budget",
    "reserve_ai_cost",
    "scrub_secrets",
    "settle_ai_budget",
    "settle_ai_cost",
]
