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
from apps.content.recommendations import (
    ContentRecommendationError,
    validate_recommendation_snapshot,
)
from integrations.ai.providers import provider_registry

from .models import AIRun, PromptVersion, ai_audit_writes


MAX_PROMPT_CHARS = 50_000
MAX_OUTPUT_BYTES = 1_000_000
JOB_PROMPT_PURPOSES = {
    Job.Type.CONTENT_GENERATE: "CONTENT_GENERATE",
    Job.Type.CONTENT_RECOMMEND: "CONTENT_RECOMMEND",
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
    facts = snapshot.get("verified_product_facts") or []
    if facts:
        fact_payload = [
            {"field_name": item["field_name"], "value": item["value"]}
            for item in facts
        ]
        rendered += "||FACTS:" + json.dumps(
            fact_payload, ensure_ascii=False, separators=(",", ":")
        )
        if len(rendered) > MAX_PROMPT_CHARS:
            raise GenerationError("prompt_too_large", "Rendered prompt exceeds the size limit.")
    return rendered


def _validate_job_input(snapshot: dict, *, organization_id, job_type: str) -> None:
    if job_type == Job.Type.CONTENT_RECOMMEND:
        try:
            validate_recommendation_snapshot(snapshot, organization_id=organization_id)
        except ContentRecommendationError as exc:
            raise GenerationPreflightError(
                "invalid_recommendation_input", str(exc)
            ) from exc
        return
    _validate_generation_input(snapshot, organization_id=organization_id)


def _render_job_prompt(template: str, snapshot: dict, *, job_type: str) -> str:
    if job_type == Job.Type.CONTENT_RECOMMEND:
        rendered = template.strip() + "||INPUT:" + json.dumps(
            snapshot, ensure_ascii=False, separators=(",", ":")
        )
        if len(rendered) > MAX_PROMPT_CHARS:
            raise GenerationError(
                "prompt_too_large", "Rendered prompt exceeds the size limit."
            )
        return rendered
    return _render_prompt(template, snapshot)


@transaction.atomic
def _create_run(*, job: Job, prompt: PromptVersion, provider: str, model: str | None = None) -> AIRun:
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


def execute_generation_job(
    job_id, *, prompt_version_id, provider_code: str | None = None,
    provider_model: str | None = None,
    worker_id="ai-worker", result_writer=None,
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
    _validate_job_input(
        snapshot, organization_id=job.organization_id, job_type=job.type
    )
    try:
        rendered = _render_job_prompt(prompt.template, snapshot, job_type=job.type)
    except GenerationError as exc:
        raise GenerationPreflightError(exc.code, str(exc)) from exc
    try:
        output_validator_class = validator_for(prompt.output_schema)
        output_validator_class.check_schema(prompt.output_schema)
        output_validator = output_validator_class(prompt.output_schema)
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
        run = _create_run(
            job=claimed, prompt=prompt, provider=provider_name, model=provider_model,
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
    try:
        output = scrub_secrets(provider.generate(prompt=rendered, schema=prompt.output_schema))
        if not isinstance(output, dict):
            raise GenerationError("invalid_provider_output", "Provider output must be an object.")
        encoded = json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise GenerationError("output_too_large", "Provider output exceeds the size limit.")
        output_validator.validate(output)
    except GenerationError as exc:
        error = {"code": exc.code, "message": str(exc)}
    except JSONSchemaValidationError:
        error = {
            "code": "invalid_provider_output",
            "message": "Provider output did not match the required schema.",
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
    return _record_failure(
        run.id, job_id=claimed.id, claim_token=token, error=error
    )
