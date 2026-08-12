from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.jobs.models import Job
from apps.jobs.services import JobService
from integrations.ai.providers import ProviderCallError, ProviderResult

from .budget import BudgetExceeded, calculate_actual_cost, reconcile_usage, reserve_budget
from .models import (
    AIProviderCall,
    AIRun,
    AIUsageAttempt,
    PromptVersion,
    ai_audit_writes,
)
from .orchestration import ProviderExecution, _safe_metadata
from .routing import create_execution_intent, route_ai_work


@dataclass(frozen=True)
class SmokeOutcome:
    passed: bool
    run_id: object
    model: str
    thinking_enabled: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
    error_code: str = ""


def _prompt_version():
    with transaction.atomic(), ai_audit_writes():
        prompt, _ = PromptVersion.objects.get_or_create(
            purpose="DEEPSEEK_SMOKE",
            version=1,
            defaults={
                "code": "deepseek-smoke-v1",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "template": "Administrator-approved smoke check.",
                "output_schema": {},
                "status": PromptVersion.Status.PUBLISHED,
            },
        )
    return prompt


def _provider_call(provider, *, prompt, schema, execution):
    """Return values only so provider exceptions cannot reach the CLI graph."""
    try:
        result = provider.generate(prompt=prompt, schema=schema, execution=execution)
    except ProviderCallError as error:
        return None, error.code
    except Exception:
        return None, "provider_error"
    if not isinstance(result, ProviderResult):
        return None, "invalid_provider_contract"
    return result, ""


def run_audited_deepseek_smoke(
    *, organization, provider, prompt: str, schema: dict, check_code: str
) -> SmokeOutcome:
    snapshot = {
        "organization_id": str(organization.id),
        "smoke_check": check_code,
    }
    decision = route_ai_work(job_type=Job.Type.CONTENT_GENERATE, snapshot=snapshot)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=snapshot,
        idempotency_key=f"deepseek-smoke:{check_code}:{uuid4()}",
        max_attempts=1,
    )
    intent = create_execution_intent(
        job=job,
        decision=decision,
        provider_prompt=prompt,
        provider_schema=schema,
        prompt_purpose="DEEPSEEK_SMOKE",
    )
    claimed = JobService.claim(worker_id="deepseek-smoke-cli", job_id=job.id)
    prompt_version = _prompt_version()
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization,
            job=claimed,
            job_attempt=claimed.attempt,
            prompt_version=prompt_version,
            provider="deepseek",
            model=intent.model,
            input_snapshot=snapshot,
            status=AIRun.Status.RUNNING,
            started_at=timezone.now(),
        )
    execution = ProviderExecution(
        organization_id=organization.id,
        model=intent.model,
        thinking_enabled=intent.thinking_enabled,
        max_output_tokens=intent.max_output_tokens,
        timeout_seconds=intent.timeout_seconds,
        policy_code=intent.policy_code,
        policy_version=intent.policy_version,
    )
    try:
        usage = reserve_budget(intent, run)
    except BudgetExceeded as error:
        return _fail_without_exception(
            run=run, job=claimed, code=str(error), usage=None, call=None
        )
    call = AIProviderCall.objects.create(
        run=run,
        generation=1,
        phase=AIProviderCall.Phase.NORMAL,
        status=AIProviderCall.Status.CALLING,
        reserved_usd=intent.reserved_cost_usd,
        lease_token=uuid4(),
        lease_expires_at=timezone.now(),
    )
    result, error_code = _provider_call(
        provider, prompt=prompt, schema=schema, execution=execution
    )
    if error_code:
        return _fail_without_exception(
            run=run, job=claimed, code=error_code, usage=usage, call=call
        )
    metadata = _safe_metadata(result.metadata, intent=intent)
    usage_counts = {
        key: _safe_token(metadata.get(key))
        for key in ("input_tokens", "output_tokens", "cache_hit_tokens")
    }
    try:
        cost = calculate_actual_cost(model=intent.model, metadata=usage_counts)
    except ValueError:
        return _fail_without_exception(
            run=run,
            job=claimed,
            code="deepseek_invalid_usage",
            usage=usage,
            call=call,
        )
    now = timezone.now()
    call.status = AIProviderCall.Status.SUCCEEDED
    call.actual_usd = min(cost, call.reserved_usd)
    call.input_tokens = usage_counts["input_tokens"]
    call.output_tokens = usage_counts["output_tokens"]
    call.cache_hit_tokens = usage_counts["cache_hit_tokens"]
    call.finish_reason = str(metadata.get("finish_reason", ""))[:64]
    call.duration_ms = _safe_token(metadata.get("duration_ms"))
    call.request_id = str(metadata.get("request_id", ""))[:128]
    call.lease_token = None
    call.lease_expires_at = None
    call.finished_at = now
    call.save(update_fields=[
        "status", "actual_usd", "input_tokens", "output_tokens",
        "cache_hit_tokens", "finish_reason", "duration_ms", "request_id",
        "lease_token", "lease_expires_at", "finished_at",
    ])
    reconcile_usage(usage, usage_counts, AIUsageAttempt.Status.SUCCEEDED)
    run.status = AIRun.Status.SUCCEEDED
    run.output_json = result.output
    run.provider_metadata = {"provider_code": "deepseek", **metadata}
    run.finished_at = now
    with ai_audit_writes():
        run.save(update_fields=["status", "output_json", "provider_metadata", "finished_at"])
    JobService.succeed(
        job.id, claim_token=claimed.claim_token, result_reference={"ai_run_id": str(run.id)}
    )
    return SmokeOutcome(
        passed=True,
        run_id=run.id,
        model=intent.model,
        thinking_enabled=intent.thinking_enabled,
        input_tokens=usage_counts["input_tokens"],
        output_tokens=usage_counts["output_tokens"],
        cache_hit_tokens=usage_counts["cache_hit_tokens"],
        estimated_cost_usd=cost,
    )


def _fail_without_exception(*, run, job, code, usage, call):
    now = timezone.now()
    if call is not None:
        call.status = AIProviderCall.Status.FAILED
        call.actual_usd = call.reserved_usd
        call.lease_token = None
        call.lease_expires_at = None
        call.finished_at = now
        call.save(update_fields=[
            "status", "actual_usd", "lease_token", "lease_expires_at", "finished_at"
        ])
    if usage is not None:
        reconcile_usage(usage, {}, AIUsageAttempt.Status.FAILED)
    run.status = AIRun.Status.FAILED
    run.error = {"code": code}
    run.finished_at = now
    with ai_audit_writes():
        run.save(update_fields=["status", "error", "finished_at"])
    JobService.fail(job.id, claim_token=job.claim_token, error={"code": code})
    return SmokeOutcome(
        passed=False,
        run_id=run.id,
        model=run.model,
        thinking_enabled=False,
        error_code=code,
    )


def _safe_token(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
