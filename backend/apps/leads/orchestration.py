from __future__ import annotations

import hashlib
import hmac
import json
from string import Formatter
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from jsonschema import ValidationError as JSONSchemaValidationError

from apps.ai.models import AIRun, PromptVersion
from apps.ai.orchestration import (
    MAX_PROMPT_CHARS,
    GenerationError,
    GenerationPreflightError,
    execute_generation_job,
)
from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError
from apps.knowledge.services import validate_frozen_ontology_snapshot
from apps.sources.models import SourceEvidence

from .models import LeadAnalysisBinding, LeadCandidate
from .schemas import (
    LEAD_ANALYSIS_OUTPUT_SCHEMA,
    frozen_source_evidence_errors,
    lead_analysis_errors,
)
from .services import LeadService


def _snapshot_digest(snapshot_without_digest: dict[str, object]) -> str:
    encoded = json.dumps(
        snapshot_without_digest,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_lead_input(snapshot: dict, *, organization_id) -> None:
    if not isinstance(snapshot, dict):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen lead-analysis input must be an object."
        )
    frozen = json.loads(json.dumps(snapshot))
    digest = frozen.pop("integrity_sha256", None)
    expected_fields = {
        "schema",
        "organization_id",
        "lead_candidate_id",
        "candidate_status_at_start",
        "analysis_lease_id",
        "analysis_lease_version",
        "candidate",
        "evidence",
        "ontology_snapshot",
        "capability_bindings",
    }
    if (
        set(frozen) != expected_fields
        or frozen.get("schema") != "LEAD_ANALYSIS_INPUT_V1"
        or frozen.get("organization_id") != str(organization_id)
        or not isinstance(digest, str)
        or not hmac.compare_digest(digest, _snapshot_digest(frozen))
    ):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input",
            "Frozen lead-analysis input failed its integrity contract.",
        )
    if set(frozen.get("candidate", {})) != {
        "company_name",
        "company_domain",
        "country_hint",
    }:
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen candidate fields are invalid."
        )
    try:
        UUID(str(frozen["analysis_lease_id"]))
    except (TypeError, ValueError):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen analysis lease is invalid."
        ) from None
    if (
        frozen["candidate_status_at_start"]
        not in {LeadCandidate.Status.DISCOVERED, LeadCandidate.Status.ANALYZED}
        or not isinstance(frozen["analysis_lease_version"], int)
        or isinstance(frozen["analysis_lease_version"], bool)
        or frozen["analysis_lease_version"] < 1
    ):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen analysis lease metadata is invalid."
        )
    candidate = LeadCandidate.objects.filter(
        pk=frozen["lead_candidate_id"],
        organization_id=organization_id,
    ).first()
    if candidate is None or candidate.status not in {
        LeadCandidate.Status.ANALYZING,
        LeadCandidate.Status.ANALYZED,
    }:
        raise GenerationPreflightError(
            "lead_candidate_unavailable", "Lead candidate is unavailable for analysis."
        )
    if str(candidate.analysis_lease_token) != str(frozen["analysis_lease_id"]):
        raise GenerationPreflightError(
            "lead_analysis_lease_lost",
            "Lead candidate is owned by another analysis.",
        )
    evidence_rows = frozen.get("evidence")
    if frozen_source_evidence_errors(evidence_rows, organization_id=organization_id):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen source evidence is invalid."
        )
    evidence_ids = [row["id"] for row in evidence_rows]
    if SourceEvidence.objects.filter(
        pk__in=evidence_ids,
        organization_id=organization_id,
    ).count() != len(evidence_ids):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen source evidence is unavailable."
        )
    try:
        ontology = validate_frozen_ontology_snapshot(
            frozen.get("ontology_snapshot"),
            organization_id=organization_id,
        )
    except ValidationError as error:
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen ontology snapshot is invalid."
        ) from error
    capability_rows = {
        row["code"]: row
        for row in ontology["concept_versions"]
        if row["concept_type"] == "CAPABILITY"
    }
    frozen_knowledge_ids = {
        row["evidence_id"] for row in ontology["evidence_references"]
    }
    bindings = frozen.get("capability_bindings")
    if not isinstance(bindings, list):
        raise GenerationPreflightError(
            "invalid_lead_analysis_input", "Frozen capability bindings are invalid."
        )
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {
            "capability_code",
            "capability_concept_id",
            "knowledge_evidence_ids",
        }:
            raise GenerationPreflightError(
                "invalid_lead_analysis_input", "Frozen capability bindings are invalid."
            )
        concept = capability_rows.get(binding["capability_code"])
        evidence_ids_for_capability = binding["knowledge_evidence_ids"]
        if (
            concept is None
            or binding["capability_concept_id"] != concept["concept_id"]
            or not isinstance(evidence_ids_for_capability, list)
            or len(evidence_ids_for_capability) != len(set(evidence_ids_for_capability))
            or not set(evidence_ids_for_capability) <= frozen_knowledge_ids
        ):
            raise GenerationPreflightError(
                "invalid_lead_analysis_input", "Frozen capability bindings are invalid."
            )


def _render_lead_prompt(template: str, snapshot: dict) -> str:
    context = {
        "input_json": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        "company_name": snapshot["candidate"]["company_name"],
        "evidence_json": json.dumps(snapshot["evidence"], ensure_ascii=False, sort_keys=True),
        "ontology_json": json.dumps(
            snapshot["ontology_snapshot"], ensure_ascii=False, sort_keys=True
        ),
    }
    required = {field for _, field, _, _ in Formatter().parse(template) if field}
    if required - context.keys():
        raise GenerationError(
            "invalid_prompt_template", "Lead prompt template has unknown variables."
        )
    try:
        rendered = template.format_map(context)
    except (KeyError, ValueError, AttributeError) as error:
        raise GenerationError(
            "invalid_prompt_template", "Lead prompt rendering failed."
        ) from error
    if len(rendered) > MAX_PROMPT_CHARS:
        raise GenerationError("prompt_too_large", "Rendered prompt exceeds the size limit.")
    return rendered


def _validate_lead_output(output: dict, *, snapshot: dict) -> None:
    errors = lead_analysis_errors(output, snapshot=snapshot)
    if errors:
        raise JSONSchemaValidationError("; ".join(errors[:10]))


def _snapshot_recovery_candidate_id(snapshot, *, organization_id, binding=None):
    if isinstance(snapshot, dict):
        frozen = json.loads(json.dumps(snapshot))
        digest = frozen.pop("integrity_sha256", None)
        if (
            frozen.get("organization_id") == str(organization_id)
            and isinstance(digest, str)
            and hmac.compare_digest(digest, _snapshot_digest(frozen))
        ):
            return frozen.get("lead_candidate_id")
    if (
        binding is not None
        and binding.organization_id == organization_id
        and binding.job.organization_id == organization_id
    ):
        return binding.candidate_id
    return None


def _recover_candidate(snapshot, *, organization_id, binding=None) -> None:
    if not isinstance(snapshot, dict):
        return
    candidate_id = _snapshot_recovery_candidate_id(
        snapshot,
        organization_id=organization_id,
        binding=binding,
    )
    if candidate_id is None:
        return
    LeadService.recover_failed_analysis(
        organization_id=organization_id,
        candidate_id=candidate_id,
        started_from=snapshot.get("candidate_status_at_start"),
        analysis_lease_token=snapshot.get("analysis_lease_id"),
    )


@transaction.atomic
def _terminalize_preflight_failure(job_id) -> bool:
    claimed = JobService.claim(
        worker_id="lead-analysis-preflight",
        job_id=job_id,
    )
    if claimed is None:
        return False
    failed = JobService.fail(
        claimed.id,
        claim_token=claimed.claim_token,
        error={"code": "job_error"},
    )
    return failed.status == Job.Status.FAILED


def _bound_prompt(job, prompt_version_id):
    binding = (
        LeadAnalysisBinding.objects.select_related("job", "candidate", "prompt_version")
        .filter(job_id=job.id)
        .first()
    )
    snapshot = job.input_snapshot
    frozen = json.loads(json.dumps(snapshot)) if isinstance(snapshot, dict) else {}
    digest = frozen.pop("integrity_sha256", None)
    expected_fields = {
        "schema",
        "organization_id",
        "lead_candidate_id",
        "candidate_status_at_start",
        "analysis_lease_id",
        "analysis_lease_version",
        "candidate",
        "evidence",
        "ontology_snapshot",
        "capability_bindings",
    }
    snapshot_integrity_valid = (
        set(frozen) == expected_fields
        and frozen.get("schema") == "LEAD_ANALYSIS_INPUT_V1"
        and isinstance(digest, str)
        and hmac.compare_digest(digest, _snapshot_digest(frozen))
    )
    valid = (
        binding is not None
        and binding.organization_id == job.organization_id
        and binding.job.organization_id == job.organization_id
        and binding.candidate.organization_id == job.organization_id
        and isinstance(snapshot, dict)
        and snapshot.get("organization_id") == str(job.organization_id)
        and snapshot.get("lead_candidate_id") == str(binding.candidate_id)
        and snapshot_integrity_valid
        and binding.prompt_version.purpose == "LEAD_ANALYZE"
        and binding.prompt_version.status == PromptVersion.Status.PUBLISHED
        and binding.prompt_version.output_schema == LEAD_ANALYSIS_OUTPUT_SCHEMA
    )
    if not valid:
        raise GenerationPreflightError(
            "invalid_lead_analysis_binding",
            "Durable lead-analysis binding is missing or inconsistent.",
        )
    if (
        prompt_version_id is not None
        and str(prompt_version_id) != str(binding.prompt_version_id)
    ):
        raise GenerationPreflightError(
            "lead_prompt_binding_mismatch",
            "Requested prompt does not match the durable bound prompt.",
        )
    return binding, binding.prompt_version


def execute_lead_analysis_job(
    job_id,
    prompt_version_id=None,
    provider_code: str | None = None,
) -> AIRun:
    job = Job.objects.get(pk=job_id)
    if job.type != Job.Type.LEAD_ANALYZE:
        raise GenerationPreflightError(
            "job_type_mismatch", "Job is not a lead-analysis job."
        )
    binding = None
    try:
        binding, prompt = _bound_prompt(job, prompt_version_id)
        if provider_code is not None and provider_code.strip().lower() != prompt.provider.lower():
            raise GenerationPreflightError(
                "lead_provider_binding_mismatch",
                "Requested provider does not match the durable bound prompt.",
            )
    except GenerationPreflightError:
        binding = (
            LeadAnalysisBinding.objects.select_related("job", "candidate")
            .filter(job_id=job.id)
            .first()
        )
        if _terminalize_preflight_failure(job.id):
            _recover_candidate(
                job.input_snapshot,
                organization_id=job.organization_id,
                binding=binding,
            )
        raise
    if job.status == Job.Status.RETRY_QUEUED:
        LeadService.resume_analysis_retry(
            organization_id=job.organization_id,
            candidate_id=job.input_snapshot.get("lead_candidate_id"),
            started_from=job.input_snapshot.get("candidate_status_at_start"),
            analysis_lease_token=job.input_snapshot.get("analysis_lease_id"),
        )

    def result_writer(run, output):
        insight = LeadService.record_analysis_output(run=run, output=output)
        return {
            "lead_candidate_id": str(insight.candidate_id),
            "lead_insight_id": str(insight.id),
            "ai_run_id": str(run.id),
        }

    try:
        run = execute_generation_job(
            job_id,
            prompt_version_id=prompt.id,
            provider_code=prompt.provider,
            worker_id="lead-analysis-worker",
            result_writer=result_writer,
            input_validator=_validate_lead_input,
            prompt_renderer=_render_lead_prompt,
            output_validator=_validate_lead_output,
            invalid_output_retries=1,
            invalid_output_message=(
                "Provider output did not match the required lead-analysis schema."
            ),
        )
    except StaleJobWorkerError:
        raise
    except GenerationPreflightError:
        if _terminalize_preflight_failure(job.id):
            _recover_candidate(
                job.input_snapshot,
                organization_id=job.organization_id,
                binding=binding,
            )
        raise
    if run.status in {AIRun.Status.FAILED, AIRun.Status.CANCELED}:
        _recover_candidate(
            job.input_snapshot,
            organization_id=job.organization_id,
            binding=binding,
        )
    return run


__all__ = ["execute_lead_analysis_job"]
