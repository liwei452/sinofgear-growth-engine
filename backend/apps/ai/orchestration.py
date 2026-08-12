import json
from dataclasses import dataclass
from enum import Enum
from datetime import timedelta
from decimal import Decimal
from string import Formatter
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.utils import timezone
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for

from apps.campaigns.generation_schema import generation_input_errors
from apps.common.security import normalize_persisted_error, scrub_secrets
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError, JobService
from integrations.ai.providers import provider_registry
from integrations.ai.providers import (
    ProviderAuthenticationError,
    ProviderBalanceError,
    ProviderCallError,
    ProviderInvalidOutputError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderResult,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from .budget import (
    BudgetExceeded,
    calculate_actual_cost,
    reconcile_usage,
    reserve_additional_call,
    reserve_budget,
)
from .models import (
    AIExecutionIntent,
    AIProviderConfiguration,
    AIProviderCall,
    AIRetryDispatchOutbox,
    AIRun,
    AIUsageAttempt,
    PromptVersion,
    ai_audit_writes,
)
from .routing import (
    InputBudgetExceeded,
    build_provider_input,
    validate_frozen_provider_input,
    validate_routing_snapshot,
)


MAX_PROMPT_CHARS = 50_000
MAX_OUTPUT_BYTES = 1_000_000
JOB_PROMPT_PURPOSES = {
    Job.Type.CONTENT_GENERATE: "CONTENT_GENERATE",
    Job.Type.LEAD_ANALYZE: "LEAD_ANALYZE",
}


class GenerationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class GenerationPreflightError(GenerationError):
    """A controlled configuration/input error detected before job ownership."""


class ProviderRetryRequired(RuntimeError):
    """Controlled signal for the Celery boundary; contains no provider detail."""

    def __init__(self, *, countdown: int, retry_count: int):
        self.countdown = countdown
        self.retry_count = retry_count
        super().__init__("AI provider retry is scheduled.")


@dataclass(frozen=True)
class ProviderExecution:
    organization_id: object
    model: str
    thinking_enabled: bool
    max_output_tokens: int
    timeout_seconds: int
    policy_code: str
    policy_version: int


class ClaimOutcome(Enum):
    ACQUIRED = "ACQUIRED"
    ACTIVE = "ACTIVE"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


_SAFE_PROVIDER_METADATA = frozenset({
    "model", "request_id", "finish_reason", "input_tokens", "output_tokens",
    "cache_hit_tokens", "total_tokens", "duration_ms", "latency_ms",
})
_RETRYABLE_ERRORS = (
    ProviderRateLimitError, ProviderUnavailableError,
    ProviderNetworkError, ProviderTimeoutError,
)
MAX_TRANSPORT_RETRIES = 2
MAX_RETRY_DELAY_SECONDS = 300
CALL_LEASE_SECONDS = 180
MAX_SAFE_TOKEN_COUNT = 100_000_000
MAX_SAFE_DURATION_MS = 600_000


def _validate_generation_input(snapshot: dict, *, organization_id) -> None:
    if generation_input_errors(snapshot):
        raise GenerationPreflightError(
            "invalid_generation_input",
            "Frozen generation input does not match the required schema.",
        )
    expected = str(organization_id)
    if (
        snapshot["organization_id"] != expected
        or snapshot["ontology_snapshot"]["organization_id"] != expected
    ):
        raise GenerationPreflightError(
            "generation_input_organization_mismatch",
            "Frozen generation input does not belong to the job organization.",
        )
    if "ai_routing" in snapshot and not validate_routing_snapshot(snapshot["ai_routing"]):
        raise GenerationPreflightError(
            "invalid_generation_input", "Frozen AI routing metadata is invalid."
        )


def _approved_concept_codes(snapshot: dict) -> list[str]:
    ontology = snapshot.get("ontology_snapshot")
    if not isinstance(ontology, dict):
        raise GenerationError("invalid_ontology_snapshot", "Ontology snapshot is missing.")
    for collection in ("concept_versions", "relation_versions", "evidence_references"):
        rows = ontology.get(collection, [])
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or row.get("status") != "APPROVED" for row in rows
        ):
            raise GenerationError(
                "invalid_ontology_snapshot",
                "Ontology snapshot contains non-approved knowledge.",
            )
    return sorted(
        {str(row["code"]) for row in ontology.get("concept_versions", []) if row.get("code")}
    )


def _render_prompt(template: str, snapshot: dict) -> str:
    codes = _approved_concept_codes(snapshot)
    products = snapshot.get("products") or []
    platforms = snapshot.get("target_platforms") or []
    context = {
        "product_name": products[0].get("name_en", "") if products else "",
        "target_country": snapshot.get("target_country", ""),
        "target_platform": platforms[0].get("code", "") if platforms else "",
        "cta": snapshot.get("cta", ""),
        "concept_codes": ", ".join(codes),
    }
    required = {field for _, field, _, _ in Formatter().parse(template) if field}
    missing = sorted(required - context.keys())
    if missing:
        raise GenerationError("invalid_prompt_template", "Prompt template has unknown variables.")
    empty = sorted(
        field for field in required if field != "concept_codes" and not context[field]
    )
    if empty:
        raise GenerationError(
            "invalid_prompt_input", "Frozen generation input is missing required values."
        )
    try:
        rendered = template.format_map(context)
    except (KeyError, ValueError, AttributeError) as exc:
        raise GenerationError("invalid_prompt_template", "Prompt rendering failed.") from exc
    if len(rendered) > MAX_PROMPT_CHARS:
        raise GenerationError("prompt_too_large", "Rendered prompt exceeds the size limit.")
    return rendered


@transaction.atomic
def _create_run(
    *, job: Job, prompt: PromptVersion, provider: str, model=None, input_snapshot=None
) -> AIRun:
    existing = AIRun.objects.filter(job=job, job_attempt=job.attempt).first()
    if existing:
        return existing
    with ai_audit_writes():
        try:
            return AIRun.objects.create(
                organization=job.organization,
                job=job,
                job_attempt=job.attempt,
                prompt_version=prompt,
                provider=provider,
                model=model or prompt.model,
                input_snapshot=scrub_secrets(
                    job.input_snapshot if input_snapshot is None else input_snapshot
                ),
                status=AIRun.Status.RUNNING,
                started_at=timezone.now(),
            )
        except IntegrityError:
            return AIRun.objects.get(job=job, job_attempt=job.attempt)


@transaction.atomic
def _record_success(
    run_id, *, job_id, claim_token, output: dict, metadata: dict,
    usage_attempt=None, result_writer=None
) -> AIRun:
    job = Job.objects.select_for_update().get(pk=job_id)
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    if job.status == Job.Status.CANCELED:
        if usage_attempt is not None:
            reconcile_status = (
                AIUsageAttempt.Status.FAILED
                if AIProviderCall.objects.filter(
                    run=run,
                    status__in=[
                        AIProviderCall.Status.CALLING,
                        AIProviderCall.Status.SUCCEEDED,
                        AIProviderCall.Status.AMBIGUOUS,
                    ],
                ).exists()
                else AIUsageAttempt.Status.CANCELED
            )
            _reconcile_from_calls(usage_attempt, run, reconcile_status)
            usage_attempt = None
        return _record_canceled_run(run)
    run.status = AIRun.Status.SUCCEEDED
    run.output_json = output
    run.confidence = Decimal("1.0000")
    run.provider_metadata = {"provider_code": run.provider, **metadata}
    run.next_retry_at = None
    run.error = None
    run.finished_at = timezone.now()
    with ai_audit_writes():
        run.save(
            update_fields=[
                "status", "output_json", "confidence", "provider_metadata",
                "error", "finished_at", "next_retry_at",
            ]
        )
    result_reference = (
        result_writer(run, output)
        if result_writer is not None
        else {"ai_run_id": str(run.id)}
    )
    JobService.succeed(
        job_id,
        claim_token=claim_token,
        result_reference=result_reference,
    )
    if usage_attempt is not None:
        _reconcile_from_calls(
            usage_attempt, run, AIUsageAttempt.Status.SUCCEEDED, metadata
        )
    return run


@transaction.atomic
def _record_failure(
    run_id, *, job_id, claim_token, error: dict, usage_attempt=None,
    usage_metadata=None,
) -> AIRun:
    job = Job.objects.select_for_update().get(pk=job_id)
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    if job.status == Job.Status.CANCELED:
        if usage_attempt is not None:
            call_started = AIProviderCall.objects.filter(
                run=run,
                status__in=[
                    AIProviderCall.Status.CALLING,
                    AIProviderCall.Status.SUCCEEDED,
                    AIProviderCall.Status.AMBIGUOUS,
                ],
            ).exists()
            _reconcile_from_calls(
                usage_attempt, run,
                AIUsageAttempt.Status.FAILED if call_started
                else AIUsageAttempt.Status.CANCELED,
            )
        return _record_canceled_run(run)
    run.status = AIRun.Status.FAILED
    run.output_json = None
    normalized_error = normalize_persisted_error(error)
    run.error = normalized_error
    run.finished_at = timezone.now()
    run.next_retry_at = None
    with ai_audit_writes():
        run.save(
            update_fields=["status", "output_json", "error", "finished_at", "next_retry_at"]
        )
    JobService.fail(job_id, claim_token=claim_token, error=normalized_error)
    if usage_attempt is not None:
        _reconcile_from_calls(usage_attempt, run, AIUsageAttempt.Status.FAILED)
    return run


def _record_canceled_run(run: AIRun, *, usage_attempt=None) -> AIRun:
    run.status = AIRun.Status.CANCELED
    run.output_json = None
    run.confidence = None
    run.provider_metadata = {}
    run.error = normalize_persisted_error({"code": "job_canceled"})
    run.finished_at = timezone.now()
    run.next_retry_at = None
    with ai_audit_writes():
        run.save(
            update_fields=[
                "status", "output_json", "confidence", "provider_metadata",
                "error", "finished_at", "next_retry_at",
            ]
        )
    if usage_attempt is not None:
        reconcile_usage(usage_attempt, {}, AIUsageAttempt.Status.CANCELED)
    return run


@transaction.atomic
def _reconcile_orphaned_run(*, job_id, run_id) -> AIRun:
    """Converge a crashed RUNNING audit row to its already-terminal Job."""
    job = Job.objects.select_for_update().get(pk=job_id)
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if (
        run.status != AIRun.Status.RUNNING
        or run.job_attempt != job.attempt
    ):
        return run
    if job.status == Job.Status.CANCELED:
        usage_attempt = AIUsageAttempt.objects.select_for_update().filter(run=run).first()
        now = timezone.now()
        for call in AIProviderCall.objects.select_for_update().filter(
            run=run, status=AIProviderCall.Status.CALLING
        ):
            call.status = AIProviderCall.Status.AMBIGUOUS
            call.actual_usd = call.reserved_usd
            call.actual_usd = call.reserved_usd
            call.lease_token = None
            call.lease_expires_at = None
            call.finished_at = now
            call.save(update_fields=[
                "status", "actual_usd", "lease_token", "lease_expires_at",
                "finished_at",
            ])
        if usage_attempt is not None and usage_attempt.reconciled_at is None:
            started = AIProviderCall.objects.filter(run=run).exclude(
                status=AIProviderCall.Status.CANCELED_PRE_CALL
            ).exists()
            _reconcile_from_calls(
                usage_attempt, run,
                AIUsageAttempt.Status.FAILED if started
                else AIUsageAttempt.Status.CANCELED,
            )
        AIRetryDispatchOutbox.objects.filter(run=run).exclude(
            status=AIRetryDispatchOutbox.Status.ACKED
        ).update(status=AIRetryDispatchOutbox.Status.ACKED, acknowledged_at=now,
                 lease_token=None, lease_expires_at=None)
        return _record_canceled_run(run)
    if job.status == Job.Status.FAILED:
        run.status = AIRun.Status.FAILED
        run.output_json = None
        run.confidence = None
        run.provider_metadata = {}
        run.error = normalize_persisted_error(
            job.error or {"code": "provider_error"}
        )
        run.finished_at = job.finished_at or timezone.now()
        with ai_audit_writes():
            run.save(
                update_fields=[
                    "status",
                    "output_json",
                    "confidence",
                    "provider_metadata",
                    "error",
                    "finished_at",
                ]
            )
    return run


def _validate_job_routing(job, snapshot) -> None:
    intent = AIExecutionIntent.objects.filter(job=job).first()
    routing = snapshot.get("ai_routing") if isinstance(snapshot, dict) else None
    if intent is None and routing is None:
        return
    if intent is None or not validate_routing_snapshot(routing, intent=intent):
        raise GenerationPreflightError(
            "invalid_ai_routing", "Frozen AI routing does not match its execution intent."
        )


def _execution_from_intent(intent: AIExecutionIntent) -> ProviderExecution:
    return ProviderExecution(
        organization_id=intent.organization_id,
        model=intent.model,
        thinking_enabled=intent.thinking_enabled,
        max_output_tokens=intent.max_output_tokens,
        timeout_seconds=intent.timeout_seconds,
        policy_code=intent.policy_code,
        policy_version=intent.policy_version,
    )


def _safe_metadata(metadata, *, intent) -> dict:
    if not isinstance(metadata, dict):
        return {"model": intent.model}
    result = {
        key: value for key, value in metadata.items()
        if key in _SAFE_PROVIDER_METADATA
        and (value is None or isinstance(value, (str, int, float)))
        and not isinstance(value, bool)
    }
    result["model"] = intent.model
    return scrub_secrets(result)


def _bounded_usage_metadata(metadata) -> tuple[dict, str]:
    safe = dict(metadata) if isinstance(metadata, dict) else {}
    anomaly = ""
    for field in ("input_tokens", "output_tokens", "cache_hit_tokens", "total_tokens"):
        value = safe.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_SAFE_TOKEN_COUNT:
            safe[field] = 0
            anomaly = "deepseek_invalid_usage"
    duration = safe.get("duration_ms", safe.get("latency_ms", 0))
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 <= duration <= MAX_SAFE_DURATION_MS:
        safe["duration_ms"] = 0
        anomaly = "deepseek_invalid_usage"
    else:
        safe["duration_ms"] = int(duration)
    return safe, anomaly


def _provider_error(error) -> dict:
    if isinstance(error, ProviderCallError):
        return {"code": error.code}
    return {"code": "provider_error"}


def _retry_delay(error, retry_count: int) -> int:
    requested = (
        error.retry_after_seconds
        if isinstance(error, ProviderRateLimitError)
        else None
    )
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        requested = min(30 * (2 ** max(0, retry_count - 1)), MAX_RETRY_DELAY_SECONDS)
    return min(requested, MAX_RETRY_DELAY_SECONDS)


@transaction.atomic
def _schedule_retry(run_id, *, retry_count, countdown):
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    run.transport_retry_count = retry_count
    run.next_call_generation += 1
    run.next_retry_at = timezone.now() + timedelta(seconds=countdown)
    with ai_audit_writes():
        run.save(update_fields=[
            "transport_retry_count", "next_retry_at", "next_call_generation"
        ])
    AIRetryDispatchOutbox.objects.get_or_create(
        run=run, retry_generation=retry_count,
        defaults={"available_at": run.next_retry_at},
    )
    return run


@transaction.atomic
def _reserve_and_schedule_retry(run, usage_attempt, *, retry_count, countdown):
    # The additional reservation and visible due state commit together. A crash
    # before commit leaves neither; a crash after commit is recoverable by any
    # duplicate/periodic task delivery observing next_retry_at.
    reserve_additional_call(usage_attempt)
    return _schedule_retry(
        run.id, retry_count=retry_count, countdown=countdown
    )


@transaction.atomic
def _claim_provider_call(run, usage_attempt):
    locked_run = AIRun.objects.select_for_update().get(pk=run.pk)
    generation = locked_run.next_call_generation
    phase = locked_run.next_call_phase
    now = timezone.now()
    AIRetryDispatchOutbox.objects.filter(
        run=locked_run, status__in=[
            AIRetryDispatchOutbox.Status.PENDING,
            AIRetryDispatchOutbox.Status.DISPATCHING,
        ],
        available_at__lte=now,
    ).update(
        status=AIRetryDispatchOutbox.Status.ACKED,
        acknowledged_at=now, lease_token=None, lease_expires_at=None,
    )
    call = AIProviderCall.objects.select_for_update().filter(
        run=locked_run, generation=generation
    ).first()
    if call is not None:
        if call.status == AIProviderCall.Status.CALLING:
            if call.lease_expires_at and call.lease_expires_at > now:
                return ClaimOutcome.ACTIVE, None, None
            call.status = AIProviderCall.Status.AMBIGUOUS
            call.actual_usd = call.reserved_usd
            call.lease_token = None
            call.lease_expires_at = None
            call.finished_at = now
            call.save(update_fields=[
                "status", "actual_usd", "lease_token", "lease_expires_at", "finished_at"
            ])
            if locked_run.transport_retry_count >= MAX_TRANSPORT_RETRIES:
                return ClaimOutcome.RETRY_EXHAUSTED, None, None
            reserve_additional_call(usage_attempt)
            locked_run.transport_retry_count += 1
            locked_run.next_retry_at = None
            with ai_audit_writes():
                locked_run.save(
                    update_fields=["transport_retry_count", "next_retry_at"]
                )
            locked_run.next_call_generation += 1
            generation = locked_run.next_call_generation
            call = None
        elif call.status in {
            AIProviderCall.Status.SUCCEEDED, AIProviderCall.Status.FAILED,
            AIProviderCall.Status.AMBIGUOUS, AIProviderCall.Status.CANCELED_PRE_CALL,
        }:
            return ClaimOutcome.ACTIVE, None, None
    if call is None:
        call = AIProviderCall.objects.create(
            run=locked_run, generation=generation,
            phase=phase,
            status=AIProviderCall.Status.RESERVED,
            reserved_usd=usage_attempt.intent.reserved_cost_usd,
        )
    token = uuid4()
    call.status = AIProviderCall.Status.CALLING
    call.lease_token = token
    call.lease_expires_at = now + timedelta(
        seconds=max(CALL_LEASE_SECONDS, int(usage_attempt.intent.timeout_seconds) + 30)
    )
    call.save(update_fields=["status", "lease_token", "lease_expires_at"])
    return ClaimOutcome.ACQUIRED, call, token


@transaction.atomic
def _finish_provider_call(call_id, token, *, status, metadata=None):
    call = AIProviderCall.objects.select_for_update().get(pk=call_id)
    if call.status != AIProviderCall.Status.CALLING or call.lease_token != token:
        return call
    safe, usage_anomaly = _bounded_usage_metadata(metadata)
    call.status = status
    call.request_id = str(safe.get("request_id", ""))[:128]
    call.input_tokens = int(safe.get("input_tokens", 0))
    call.output_tokens = int(safe.get("output_tokens", 0))
    call.cache_hit_tokens = int(safe.get("cache_hit_tokens", 0))
    call.finish_reason = str(safe.get("finish_reason", ""))[:64]
    call.duration_ms = int(safe.get("duration_ms", safe.get("latency_ms", 0)))
    if usage_anomaly:
        call.anomaly_code = usage_anomaly
    if status == AIProviderCall.Status.SUCCEEDED:
        try:
            call.actual_usd = calculate_actual_cost(
                model=call.run.model, metadata=safe
            )
        except ValueError:
            call.actual_usd = call.reserved_usd
        if call.actual_usd > call.reserved_usd:
            call.actual_usd = call.reserved_usd
            call.anomaly_code = "deepseek_usage_exceeds_reservation"
    elif status in {
        AIProviderCall.Status.FAILED, AIProviderCall.Status.AMBIGUOUS
    }:
        call.actual_usd = call.reserved_usd
    else:
        call.actual_usd = Decimal("0")
    call.lease_token = None
    call.lease_expires_at = None
    call.finished_at = timezone.now()
    call.save(update_fields=[
        "status", "request_id", "input_tokens", "output_tokens",
        "cache_hit_tokens", "finish_reason", "duration_ms", "lease_token",
        "lease_expires_at", "finished_at", "actual_usd", "anomaly_code",
    ])
    return call


def _repair_prompt(prompt: str) -> str:
    return (
        prompt
        + "\n\nREPAIR_INSTRUCTION: Return one JSON object that exactly matches the "
          "frozen JSON Schema. Do not include explanations or markdown."
    )


def _aggregate_call_actual(run) -> Decimal:
    total = Decimal("0")
    for call in AIProviderCall.objects.filter(run=run):
        if call.status == AIProviderCall.Status.CANCELED_PRE_CALL:
            continue
        if call.status == AIProviderCall.Status.SUCCEEDED:
            total += call.actual_usd
        elif call.status in {
            AIProviderCall.Status.FAILED, AIProviderCall.Status.AMBIGUOUS,
            AIProviderCall.Status.CALLING,
        }:
            total += call.reserved_usd
    return total


def _reconcile_from_calls(usage_attempt, run, status, metadata=None):
    usage_attempt.refresh_from_db()
    total_reserved = usage_attempt.reserved_usd + usage_attempt.additional_reserved_usd
    call_reserved = sum(
        (row.reserved_usd for row in AIProviderCall.objects.filter(run=run)),
        Decimal("0"),
    )
    anomaly = call_reserved > total_reserved
    actual = min(_aggregate_call_actual(run), total_reserved)
    reconcile_usage(
        usage_attempt, metadata or {}, status,
        actual_override=actual,
    )
    return "deepseek_usage_exceeds_reservation" if anomaly else ""


def execute_generation_job(
    job_id, *, prompt_version_id, provider_code: str | None = None,
    worker_id="ai-worker", result_writer=None, input_validator=None,
    prompt_renderer=None, output_validator=None, invalid_output_retries=0,
    invalid_output_message="Provider output did not match the required schema.",
    input_snapshot=None,
) -> AIRun:
    job = Job.objects.get(pk=job_id)
    existing = AIRun.objects.filter(job_id=job_id).order_by("-job_attempt").first()
    if (
        existing
        and existing.job_attempt == job.attempt
        and existing.status in {
            AIRun.Status.RUNNING, AIRun.Status.SUCCEEDED,
            AIRun.Status.FAILED, AIRun.Status.CANCELED,
        }
    ):
        if existing.status == AIRun.Status.RUNNING and job.status in {
            Job.Status.CANCELED,
            Job.Status.FAILED,
        }:
            return _reconcile_orphaned_run(job_id=job.id, run_id=existing.id)
        retry_due = (
            existing.status == AIRun.Status.RUNNING
            and job.status == Job.Status.RUNNING
            and existing.next_retry_at is not None
            and existing.next_retry_at <= timezone.now()
        )
        if not retry_due:
            return existing

    intent = AIExecutionIntent.objects.filter(job=job).first()
    frozen_prompt_id = (
        intent.prompt_version_id_snapshot
        if intent is not None and intent.prompt_version_id_snapshot
        else prompt_version_id
    )
    try:
        prompt_query = PromptVersion.objects.filter(pk=frozen_prompt_id)
        if intent is None:
            prompt_query = prompt_query.filter(status=PromptVersion.Status.PUBLISHED)
        prompt = prompt_query.get()
    except PromptVersion.DoesNotExist as exc:
        raise GenerationPreflightError(
            "prompt_not_available", "Published prompt version is not available."
        ) from exc
    expected_purpose = JOB_PROMPT_PURPOSES.get(job.type)
    actual_purpose = intent.prompt_purpose if intent is not None else prompt.purpose
    if expected_purpose is None or actual_purpose != expected_purpose:
        raise GenerationPreflightError(
            "prompt_purpose_mismatch",
            "Prompt purpose is not compatible with the job type.",
        )
    routing = job.input_snapshot.get("ai_routing") if isinstance(job.input_snapshot, dict) else None
    if intent is not None:
        if not validate_routing_snapshot(routing, intent=intent):
            raise GenerationPreflightError(
                "invalid_ai_routing", "Frozen AI routing does not match its execution intent."
            )
        if provider_code is not None and provider_code.strip().lower() != intent.provider:
            raise GenerationPreflightError(
                "provider_binding_mismatch", "Requested provider does not match the frozen intent."
            )
        provider_name = intent.provider
        if provider_name == "deepseek" and not AIProviderConfiguration.objects.filter(
            organization_id=job.organization_id,
            connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
            operation_token__isnull=True,
            operation_started_at__isnull=True,
        ).exists():
            raise GenerationPreflightError(
                "deepseek_not_connected", "AI provider is not connected."
            )
    else:
        provider_name = provider_code or prompt.provider
        if provider_name == "deepseek" or routing is not None:
            raise GenerationPreflightError(
                "invalid_ai_routing", "Frozen AI execution intent is missing."
            )
    try:
        provider = provider_registry.get(provider_name)
    except (TypeError, ValueError) as exc:
        raise GenerationPreflightError(
            "provider_not_available", "AI provider is not available."
        ) from exc
    if not callable(getattr(provider, "generate", None)):
        raise GenerationPreflightError(
            "provider_not_available", "AI provider is not available."
        )
    snapshot = scrub_secrets(
        job.input_snapshot if input_snapshot is None else input_snapshot
    )
    _validate_job_routing(job, snapshot)
    if input_validator is None:
        _validate_generation_input(snapshot, organization_id=job.organization_id)
    else:
        input_validator(snapshot, organization_id=job.organization_id)
    if intent is not None:
        if not validate_frozen_provider_input(intent):
            raise GenerationPreflightError(
                "invalid_frozen_provider_input", "Frozen provider input is invalid."
            )
        rendered = intent.provider_prompt
        output_schema = intent.provider_schema
        try:
            build_provider_input(prompt=rendered, schema=output_schema, snapshot=snapshot)
        except InputBudgetExceeded as exc:
            raise GenerationPreflightError("provider_input_too_large", str(exc)) from None
    else:
        output_schema = prompt.output_schema
        try:
            rendered = (
                _render_prompt(prompt.template, snapshot)
                if prompt_renderer is None
                else prompt_renderer(prompt.template, snapshot)
            )
        except GenerationError as exc:
            raise GenerationPreflightError(exc.code, str(exc)) from exc
    try:
        output_validator_class = validator_for(output_schema)
        output_validator_class.check_schema(output_schema)
        schema_validator = output_validator_class(output_schema)
    except Exception as exc:
        raise GenerationPreflightError(
            "invalid_prompt_schema", "Prompt output schema is invalid."
        ) from exc

    if existing is not None and existing.status == AIRun.Status.RUNNING:
        claimed = Job.objects.get(pk=job_id)
        run = existing
        token = claimed.claim_token
        if token is None:
            return run
    else:
        claimed = JobService.claim(worker_id=worker_id, job_id=job_id)
        if claimed is None:
            existing = AIRun.objects.filter(job_id=job_id).order_by("-job_attempt").first()
            if existing:
                return existing
            raise JobConflictError(f"Job in status {job.status} cannot be claimed.")
        token = claimed.claim_token
        try:
            run = _create_run(
                job=claimed,
                prompt=prompt,
                provider=provider_name,
                model=intent.model if intent is not None else prompt.model,
                input_snapshot=snapshot,
            )
        except Exception as exc:
            JobService.fail(
                claimed.id,
                claim_token=token,
                error={"code": "ai_run_start_failed", "message": "AI audit run could not start."},
            )
            raise GenerationError(
                "ai_run_start_failed", "AI audit run could not start."
            ) from exc
    if run.status != AIRun.Status.RUNNING:
        return run
    usage_attempt = None
    execution = _execution_from_intent(intent) if intent is not None else None
    if intent is not None:
        if Job.objects.filter(pk=claimed.id, status=Job.Status.CANCELED).exists():
            return _record_canceled_run(run)
        try:
            usage_attempt = reserve_budget(intent, run)
        except BudgetExceeded as exc:
            code = str(exc) if str(exc) in {
                "deepseek_not_connected", "deepseek_daily_budget_exceeded"
            } else "deepseek_budget_unavailable"
            return _record_failure(
                run.id, job_id=claimed.id, claim_token=token, error={"code": code}
            )
        if Job.objects.filter(pk=claimed.id, status=Job.Status.CANCELED).exists():
            return _record_canceled_run(run, usage_attempt=usage_attempt)
    error = None
    output = None
    metadata = {}
    repairs_allowed = max(invalid_output_retries, 1 if intent is not None else 0)
    for invalid_attempt in range(repairs_allowed + 1):
        call = call_token = None
        if intent is not None:
            claim_outcome, call, call_token = _claim_provider_call(run, usage_attempt)
            if claim_outcome == ClaimOutcome.RETRY_EXHAUSTED:
                return _record_failure(
                    run.id, job_id=claimed.id, claim_token=token,
                    error={"code": "deepseek_retry_exhausted"},
                    usage_attempt=usage_attempt,
                )
            if claim_outcome != ClaimOutcome.ACQUIRED:
                return AIRun.objects.get(pk=run.pk)
            if Job.objects.filter(pk=claimed.id, status=Job.Status.CANCELED).exists():
                _finish_provider_call(
                    call.id, call_token,
                    status=AIProviderCall.Status.CANCELED_PRE_CALL,
                )
                return _record_canceled_run(run, usage_attempt=usage_attempt)
        try:
            result = provider.generate(
                prompt=(
                    _repair_prompt(rendered)
                    if call is not None and call.phase == AIProviderCall.Phase.REPAIR
                    else rendered
                ),
                schema=output_schema,
                **({"execution": execution} if execution is not None else {}),
            )
            if not isinstance(result, ProviderResult):
                raise GenerationError(
                    "invalid_provider_contract", "AI provider returned an unsupported result."
                )
            output = scrub_secrets(result.output)
            metadata = _safe_metadata(result.metadata, intent=intent) if intent is not None else {}
            if not isinstance(output, dict):
                raise GenerationError("invalid_provider_output", "Provider output must be an object.")
            encoded = json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
            if len(encoded) > MAX_OUTPUT_BYTES:
                raise GenerationError("output_too_large", "Provider output exceeds the size limit.")
            schema_validator.validate(output)
            if output_validator is not None:
                output_validator(output, snapshot=snapshot)
        except _RETRYABLE_ERRORS as exc:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.AMBIGUOUS
                )
            if intent is not None and run.transport_retry_count < MAX_TRANSPORT_RETRIES:
                retry_count = run.transport_retry_count + 1
                countdown = _retry_delay(exc, retry_count)
                try:
                    _reserve_and_schedule_retry(
                        run, usage_attempt, retry_count=retry_count,
                        countdown=countdown,
                    )
                except BudgetExceeded as budget_error:
                    error = {"code": str(budget_error)}
                    break
                raise ProviderRetryRequired(
                    countdown=countdown, retry_count=retry_count
                ) from None
            error = _provider_error(exc)
        except (ProviderAuthenticationError, ProviderBalanceError) as exc:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.FAILED
                )
            error = _provider_error(exc)
        except ProviderInvalidOutputError:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.FAILED
                )
            error = {
                "code": (
                    "invalid_provider_output_after_repair"
                    if call is not None and call.phase == AIProviderCall.Phase.REPAIR
                    else "invalid_provider_output"
                ),
                "message": invalid_output_message,
            }
        except GenerationError as exc:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.FAILED
                )
            error = {"code": exc.code, "message": str(exc)}
        except JSONSchemaValidationError:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.FAILED
                )
            error = {
                "code": (
                    "invalid_provider_output_after_repair"
                    if call is not None and call.phase == AIProviderCall.Phase.REPAIR
                    else "invalid_provider_output"
                ),
                "message": invalid_output_message,
            }
        except Exception:
            if call is not None:
                _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.AMBIGUOUS
                )
            error = {"code": "provider_error", "message": "AI provider generation failed."}
        else:
            if call is not None:
                finished_call = _finish_provider_call(
                    call.id, call_token, status=AIProviderCall.Status.SUCCEEDED,
                    metadata=metadata,
                )
                if finished_call.anomaly_code:
                    error = {"code": finished_call.anomaly_code}
                    break
            try:
                return _record_success(
                    run.id,
                    job_id=claimed.id,
                    claim_token=token,
                    output=output,
                    metadata=metadata,
                    usage_attempt=usage_attempt,
                    result_writer=result_writer,
                )
            except Exception:
                error = {
                    "code": "content_finalize_failed",
                    "message": "Generated content could not be finalized.",
                }
            break
        if (
            error.get("code") != "invalid_provider_output"
            or invalid_attempt >= repairs_allowed
        ):
            break
        current = Job.objects.filter(pk=claimed.id).values("status", "claim_token").first()
        if current is None or current["status"] != Job.Status.RUNNING or current["claim_token"] != token:
            break
        if intent is not None and not run.repair_attempted:
            try:
                reserve_additional_call(usage_attempt)
            except BudgetExceeded as exc:
                error = {"code": str(exc)}
                break
            run.repair_attempted = True
            run.next_call_generation += 1
            run.next_call_phase = AIProviderCall.Phase.REPAIR
            with ai_audit_writes():
                run.save(update_fields=[
                    "repair_attempted", "next_call_generation", "next_call_phase"
                ])
    return _record_failure(
        run.id, job_id=claimed.id, claim_token=token, error=error,
        usage_attempt=usage_attempt, usage_metadata=metadata,
    )
