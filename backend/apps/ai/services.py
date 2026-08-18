import json

from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator

from apps.common.security import scrub_secrets
from apps.identity.models import Organization

from .models import AIRun, PromptVersion, ai_audit_writes


class AIBudgetExceeded(RuntimeError):
    pass


AI_CALL_RESERVATION_TOKENS = 4000


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


__all__ = ["PromptVersionService", "scrub_secrets"]
