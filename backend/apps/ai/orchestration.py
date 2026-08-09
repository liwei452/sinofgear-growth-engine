import json
from decimal import Decimal
from string import Formatter

from django.db import IntegrityError, transaction
from django.utils import timezone
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for

from apps.common.security import scrub_secrets
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError, JobService
from integrations.ai.providers import provider_registry

from .models import AIRun, PromptVersion, ai_audit_writes


MAX_PROMPT_CHARS = 50_000
MAX_OUTPUT_BYTES = 1_000_000


class GenerationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
def _record_success(run_id, *, job_id, claim_token, output: dict) -> AIRun:
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
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
    JobService.succeed(
        job_id,
        claim_token=claim_token,
        result_reference={"ai_run_id": str(run.id)},
    )
    return run


@transaction.atomic
def _record_failure(run_id, *, job_id, claim_token, error: dict) -> AIRun:
    run = AIRun.objects.select_for_update().get(pk=run_id)
    if run.status != AIRun.Status.RUNNING:
        return run
    run.status = AIRun.Status.FAILED
    run.output_json = None
    run.error = scrub_secrets(error)
    run.finished_at = timezone.now()
    with ai_audit_writes():
        run.save(update_fields=["status", "output_json", "error", "finished_at"])
    JobService.fail(job_id, claim_token=claim_token, error=error)
    return run


def execute_generation_job(
    job_id, *, prompt_version_id, provider_code: str | None = None, worker_id="ai-worker"
) -> AIRun:
    existing = AIRun.objects.filter(job_id=job_id).order_by("-job_attempt").first()
    job = Job.objects.get(pk=job_id)
    if existing and existing.status in {AIRun.Status.RUNNING, AIRun.Status.SUCCEEDED}:
        return existing
    claimed = JobService.claim(worker_id=worker_id, job_id=job_id)
    if claimed is None:
        existing = AIRun.objects.filter(job_id=job_id).order_by("-job_attempt").first()
        if existing:
            return existing
        raise JobConflictError(f"Job in status {job.status} cannot be claimed.")
    token = claimed.claim_token
    prompt = PromptVersion.objects.get(
        pk=prompt_version_id, status=PromptVersion.Status.PUBLISHED
    )
    provider_name = provider_code or prompt.provider
    run = _create_run(job=claimed, prompt=prompt, provider=provider_name)
    if run.status != AIRun.Status.RUNNING:
        return run
    try:
        snapshot = scrub_secrets(run.input_snapshot)
        rendered = _render_prompt(prompt.template, snapshot)
        provider = provider_registry.get(provider_name)
        output = scrub_secrets(provider.generate(prompt=rendered, schema=prompt.output_schema))
        if not isinstance(output, dict):
            raise GenerationError("invalid_provider_output", "Provider output must be an object.")
        encoded = json.dumps(output, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_OUTPUT_BYTES:
            raise GenerationError("output_too_large", "Provider output exceeds the size limit.")
        validator = validator_for(prompt.output_schema)
        validator.check_schema(prompt.output_schema)
        validator(prompt.output_schema).validate(output)
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
        return _record_success(
            run.id,
            job_id=claimed.id,
            claim_token=token,
            output=output,
        )
    return _record_failure(
        run.id, job_id=claimed.id, claim_token=token, error=error
    )
