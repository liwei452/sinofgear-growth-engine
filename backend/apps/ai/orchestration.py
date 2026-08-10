import json
from decimal import Decimal
from string import Formatter

from django.db import IntegrityError, transaction
from django.utils import timezone
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for

from apps.campaigns.generation_schema import generation_input_errors
from apps.common.security import normalize_persisted_error, scrub_secrets
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError, JobService
from integrations.ai.providers import provider_registry

from .models import AIRun, PromptVersion, ai_audit_writes


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
def _create_run(*, job: Job, prompt: PromptVersion, provider: str) -> AIRun:
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
                model=prompt.model,
                input_snapshot=scrub_secrets(job.input_snapshot),
                status=AIRun.Status.RUNNING,
                started_at=timezone.now(),
            )
        except IntegrityError:
            return AIRun.objects.get(job=job, job_attempt=job.attempt)


@transaction.atomic
def _record_success(
    run_id, *, job_id, claim_token, output: dict, result_writer=None
) -> AIRun:
    job = Job.objects.select_for_update().get(pk=job_id)
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    if job.status == Job.Status.CANCELED:
        return _record_canceled_run(run)
    run.status = AIRun.Status.SUCCEEDED
    run.output_json = output
    run.confidence = Decimal("1.0000")
    run.provider_metadata = {"provider_code": run.provider}
    run.error = None
    run.finished_at = timezone.now()
    with ai_audit_writes():
        run.save(
            update_fields=[
                "status", "output_json", "confidence", "provider_metadata",
                "error", "finished_at",
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
    return run


@transaction.atomic
def _record_failure(run_id, *, job_id, claim_token, error: dict) -> AIRun:
    job = Job.objects.select_for_update().get(pk=job_id)
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    if job.status == Job.Status.CANCELED:
        return _record_canceled_run(run)
    run.status = AIRun.Status.FAILED
    run.output_json = None
    normalized_error = normalize_persisted_error(error)
    run.error = normalized_error
    run.finished_at = timezone.now()
    with ai_audit_writes():
        run.save(update_fields=["status", "output_json", "error", "finished_at"])
    JobService.fail(job_id, claim_token=claim_token, error=normalized_error)
    return run


def _record_canceled_run(run: AIRun) -> AIRun:
    run.status = AIRun.Status.CANCELED
    run.output_json = None
    run.confidence = None
    run.provider_metadata = {}
    run.error = normalize_persisted_error({"code": "job_canceled"})
    run.finished_at = timezone.now()
    with ai_audit_writes():
        run.save(
            update_fields=[
                "status", "output_json", "confidence", "provider_metadata",
                "error", "finished_at",
            ]
        )
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


def execute_generation_job(
    job_id, *, prompt_version_id, provider_code: str | None = None,
    worker_id="ai-worker", result_writer=None, input_validator=None,
    prompt_renderer=None, output_validator=None, invalid_output_retries=0,
    invalid_output_message="Provider output did not match the required schema.",
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
        return existing

    try:
        prompt = PromptVersion.objects.get(
            pk=prompt_version_id, status=PromptVersion.Status.PUBLISHED
        )
    except PromptVersion.DoesNotExist as exc:
        raise GenerationPreflightError(
            "prompt_not_available", "Published prompt version is not available."
        ) from exc
    expected_purpose = JOB_PROMPT_PURPOSES.get(job.type)
    if expected_purpose is None or prompt.purpose != expected_purpose:
        raise GenerationPreflightError(
            "prompt_purpose_mismatch",
            "Prompt purpose is not compatible with the job type.",
        )
    provider_name = provider_code or prompt.provider
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
    snapshot = scrub_secrets(job.input_snapshot)
    if input_validator is None:
        _validate_generation_input(snapshot, organization_id=job.organization_id)
    else:
        input_validator(snapshot, organization_id=job.organization_id)
    try:
        rendered = (
            _render_prompt(prompt.template, snapshot)
            if prompt_renderer is None
            else prompt_renderer(prompt.template, snapshot)
        )
    except GenerationError as exc:
        raise GenerationPreflightError(exc.code, str(exc)) from exc
    try:
        output_validator_class = validator_for(prompt.output_schema)
        output_validator_class.check_schema(prompt.output_schema)
        schema_validator = output_validator_class(prompt.output_schema)
    except Exception as exc:
        raise GenerationPreflightError(
            "invalid_prompt_schema", "Prompt output schema is invalid."
        ) from exc

    claimed = JobService.claim(worker_id=worker_id, job_id=job_id)
    if claimed is None:
        existing = AIRun.objects.filter(job_id=job_id).order_by("-job_attempt").first()
        if existing:
            return existing
        raise JobConflictError(f"Job in status {job.status} cannot be claimed.")
    token = claimed.claim_token
    try:
        run = _create_run(job=claimed, prompt=prompt, provider=provider_name)
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
    error = None
    output = None
    for invalid_attempt in range(invalid_output_retries + 1):
        try:
            output = scrub_secrets(provider.generate(prompt=rendered, schema=prompt.output_schema))
            if not isinstance(output, dict):
                raise GenerationError("invalid_provider_output", "Provider output must be an object.")
            encoded = json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
            if len(encoded) > MAX_OUTPUT_BYTES:
                raise GenerationError("output_too_large", "Provider output exceeds the size limit.")
            schema_validator.validate(output)
            if output_validator is not None:
                output_validator(output, snapshot=snapshot)
        except GenerationError as exc:
            error = {"code": exc.code, "message": str(exc)}
        except JSONSchemaValidationError:
            error = {
                "code": "invalid_provider_output",
                "message": invalid_output_message,
            }
        except Exception:
            error = {"code": "provider_error", "message": "AI provider generation failed."}
        else:
            try:
                return _record_success(
                    run.id,
                    job_id=claimed.id,
                    claim_token=token,
                    output=output,
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
            or invalid_attempt >= invalid_output_retries
        ):
            break
        current = Job.objects.filter(pk=claimed.id).values("status", "claim_token").first()
        if current is None or current["status"] != Job.Status.RUNNING or current["claim_token"] != token:
            break
    return _record_failure(
        run.id, job_id=claimed.id, claim_token=token, error=error
    )
