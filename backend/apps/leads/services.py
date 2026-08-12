import hashlib
import hmac
import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import uuid4, uuid5

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion
from apps.common.security import scrub_secrets
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError, JobService
from apps.sources.models import SourceEvidence
from apps.sources.services import EvidenceService

from .models import (
    LeadCandidate,
    LeadCandidateEvidence,
    LeadAnalysisBinding,
    LeadInsight,
    LeadInsightRequirement,
    LeadReview,
    LeadVersionConflict,
    lead_analysis_lease_writes,
    lead_frozen_reference_writes,
    lead_history_writes,
)
from .scoring import EvidenceGates, ScoreDimensions, score_lead


class LeadStateError(ValueError):
    pass


class LeadIdempotencyConflictError(LeadStateError):
    pass


def lead_analysis_attempt_lease(job_id, attempt):
    return uuid5(job_id, f"lead-analysis-attempt:{attempt}")


@dataclass(frozen=True)
class LeadReviewResult:
    review: LeadReview
    candidate: LeadCandidate
    insight: LeadInsight | None


def _json_copy(value, field_name):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as error:
        raise ValidationError({field_name: "Value must be JSON serializable."}) from error


def _confidence(value, field_name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError({field_name: "Confidence must be between 0 and 1."}) from error
    if not Decimal("0") <= result <= Decimal("1"):
        raise ValidationError({field_name: "Confidence must be between 0 and 1."})
    return result


def _payload_reference_id(value):
    if value is None:
        return None
    reference = getattr(value, "pk", value)
    return str(reference)


def canonical_lead_insight_output(payload) -> dict[str, object]:
    """Map the domain payload deterministically to the JSON saved on its AIRun."""
    if not isinstance(payload, dict):
        raise ValidationError("Insight output must be an object.")
    requirements = payload.get("requirements", [])
    if not isinstance(requirements, list) or any(
        not isinstance(row, dict) for row in requirements
    ):
        raise ValidationError({"requirements": "Requirements must be a list of objects."})
    canonical_requirements = []
    for row in requirements:
        canonical_requirements.append(
            {
                "requirement_concept_id": _payload_reference_id(
                    row.get("requirement_concept", row.get("requirement_concept_id"))
                ),
                "capability_concept_id": _payload_reference_id(
                    row.get("capability_concept", row.get("capability_concept_id"))
                ),
                "capability_knowledge_evidence_id": _payload_reference_id(
                    row.get(
                        "capability_knowledge_evidence",
                        row.get("capability_knowledge_evidence_id"),
                    )
                ),
                "evidence_id": _payload_reference_id(
                    row.get("evidence", row.get("evidence_id"))
                ),
                "extracted_value": row.get("extracted_value"),
                "unit": row.get("unit", ""),
            }
        )
    return _json_copy(
        {
            "dimensions": payload.get("dimensions"),
            "gates": payload.get("gates"),
            "explanation": payload.get("explanation"),
            "extracted_requirement_values": payload.get(
                "extracted_requirement_values", []
            ),
            "confidence": payload.get("confidence"),
            "ontology_snapshot": payload.get("ontology_snapshot"),
            "requirements": canonical_requirements,
        },
        "output_json",
    )


class LeadService:
    @staticmethod
    @transaction.atomic
    def create_candidate(
        *, organization, creator, company_name, company_domain, country_hint, evidence_ids
    ):
        requested = [getattr(item, "pk", item) for item in evidence_ids]
        if not requested or len(requested) != len(set(requested)):
            raise ValidationError(
                {"evidence_ids": "Evidence IDs must be a non-empty unique list."}
            )
        evidence = list(
            SourceEvidence.objects.select_for_update()
            .select_related("source_signal")
            .filter(organization=organization, pk__in=requested)
            .order_by("pk")
        )
        if {row.pk for row in evidence} != set(requested):
            raise ValidationError(
                {"evidence_ids": "Evidence is unavailable for this organization."}
            )
        if not str(company_name).strip() and not str(company_domain).strip():
            raise ValidationError(
                {"company_name": "Provide a company name or public company domain."}
            )
        candidate = LeadCandidate.objects.create(
            organization=organization,
            source_signal=evidence[0].source_signal,
            company_name=str(company_name).strip(),
            company_domain=str(company_domain).strip(),
            country_hint=str(country_hint).strip(),
            created_by=creator,
        )
        with lead_history_writes():
            for row in evidence:
                LeadCandidateEvidence.objects.create(
                    organization=organization,
                    candidate=candidate,
                    insight=None,
                    evidence=row,
                    source_signal=row.source_signal,
                )
        return candidate

    @staticmethod
    @transaction.atomic
    def begin_analysis(*, organization, candidate, expected_version=None):
        candidate_id = candidate.pk if isinstance(candidate, LeadCandidate) else candidate
        locked = LeadCandidate.objects.select_for_update().get(
            pk=candidate_id,
            organization=organization,
        )
        expected = locked.version if expected_version is None else expected_version
        if locked.version != expected:
            raise LeadVersionConflict("Lead candidate version is stale.")
        if locked.analysis_lease_token is not None:
            raise LeadStateError("Lead candidate already has an active analysis lease.")
        if locked.status not in {
            LeadCandidate.Status.DISCOVERED,
            LeadCandidate.Status.ANALYZED,
        }:
            raise LeadStateError("Lead must be discovered or analyzed before analysis starts.")
        locked.status = LeadCandidate.Status.ANALYZING
        locked.analysis_lease_token = uuid4()
        with lead_analysis_lease_writes():
            locked.save(
                update_fields=["status", "analysis_lease_token", "updated_at"]
            )
        return locked

    @staticmethod
    @transaction.atomic
    def transition(*, organization, candidate, to_status, expected_version=None):
        if to_status not in LeadCandidate.Status.values:
            raise LeadStateError("Lead status is invalid.")
        candidate_id = candidate.pk if isinstance(candidate, LeadCandidate) else candidate
        locked = LeadCandidate.objects.select_for_update().get(
            pk=candidate_id, organization=organization
        )
        expected = (
            candidate.version
            if expected_version is None and isinstance(candidate, LeadCandidate)
            else locked.version
            if expected_version is None
            else expected_version
        )
        if locked.version != expected:
            raise LeadVersionConflict("Lead candidate version is stale.")
        if locked.analysis_lease_token is not None:
            raise LeadStateError(
                "Lead candidate has an active analysis lease; manual transitions are disabled."
            )
        if to_status == LeadCandidate.Status.ANALYZING:
            raise LeadStateError("Use begin_analysis to enter ANALYZING.")
        if to_status not in LeadCandidate.B1_TRANSITIONS.get(locked.status, frozenset()):
            raise LeadStateError(f"B1 cannot transition from {locked.status} to {to_status}.")
        locked.status = to_status
        locked.save(update_fields=["status", "updated_at"])
        if isinstance(candidate, LeadCandidate):
            candidate.status = locked.status
            candidate.version = locked.version
            candidate.updated_at = locked.updated_at
            return candidate
        return locked

    @staticmethod
    @transaction.atomic
    def record_insight(
        *, organization, candidate, ai_run, evidence, payload, audited_output=None
    ):
        candidate_id = candidate.pk if isinstance(candidate, LeadCandidate) else candidate
        locked_candidate = LeadCandidate.objects.select_for_update().get(
            pk=candidate_id, organization=organization
        )
        run = AIRun.objects.select_related("job", "prompt_version").get(pk=ai_run.pk)
        if audited_output is not None:
            frozen_lease = run.input_snapshot.get("analysis_lease_id")
            if (
                not frozen_lease
                or str(locked_candidate.analysis_lease_token) != str(frozen_lease)
            ):
                raise LeadStateError("Lead analysis lease is no longer owned by this run.")
        if locked_candidate.status not in {
            LeadCandidate.Status.ANALYZING,
            LeadCandidate.Status.ANALYZED,
        }:
            raise LeadStateError("Lead must be analyzing or analyzed before recording insight.")
        if run.organization_id != locked_candidate.organization_id:
            raise ValidationError({"ai_run": "AI run must belong to the candidate organization."})
        if run.status != AIRun.Status.SUCCEEDED:
            raise ValidationError({"ai_run": "Only a successful audited AI run may create an insight."})
        if (
            run.job.organization_id != locked_candidate.organization_id
            or run.job.type != Job.Type.LEAD_ANALYZE
            or run.prompt_version.purpose != "LEAD_ANALYZE"
        ):
            raise ValidationError({"ai_run": "AI run is not an audited lead-analysis run."})
        if LeadInsight.objects.filter(ai_run=run).exists():
            raise ValidationError({"ai_run": "AI run already produced a lead insight."})
        expected_output = (
            canonical_lead_insight_output(payload)
            if audited_output is None
            else _json_copy(audited_output, "audited_output")
        )
        if run.output_json != expected_output:
            raise ValidationError(
                {"ai_run": "Insight conclusions must equal the successful AI run output."}
            )

        evidence_ids = [item.pk for item in evidence]
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValidationError({"evidence": "Insight evidence must be a non-empty unique list."})
        locked_evidence = list(
            SourceEvidence.objects.select_related("source_signal")
            .filter(pk__in=evidence_ids, organization=locked_candidate.organization)
            .order_by("pk")
        )
        if {item.pk for item in locked_evidence} != set(evidence_ids):
            raise ValidationError({"evidence": "Evidence must belong to the candidate organization."})
        frozen_ontology_snapshot = LeadService._validate_frozen_analysis_binding(
            run=run,
            candidate=locked_candidate,
            evidence=locked_evidence,
        )

        dimensions_data = payload.get("dimensions") if isinstance(payload, dict) else None
        gates_data = payload.get("gates") if isinstance(payload, dict) else None
        if not isinstance(dimensions_data, dict) or not isinstance(gates_data, dict):
            raise ValidationError("Insight payload requires dimensions and evidence gates.")
        try:
            dimensions = ScoreDimensions(**dimensions_data)
            gates = EvidenceGates(**gates_data)
        except TypeError as error:
            raise ValidationError("Insight dimensions or evidence gates are incomplete.") from error
        scored = score_lead(dimensions, gates)
        if gates.traceable_source and not locked_evidence:
            raise ValidationError({"gates": "Traceable-source gate requires evidence."})
        if gates.audited_run and run.status != AIRun.Status.SUCCEEDED:
            raise ValidationError({"gates": "Audited-run gate requires a successful AI run."})

        snapshot = _json_copy(payload.get("ontology_snapshot", {}), "ontology_snapshot")
        if snapshot != frozen_ontology_snapshot:
            raise ValidationError(
                {"ontology_snapshot": "Insight ontology must equal the frozen AI-run snapshot."}
            )
        snapshot_organization_id = snapshot.get("organization_id")
        if snapshot_organization_id is not None and str(snapshot_organization_id) != str(
            locked_candidate.organization_id
        ):
            raise ValidationError({"ontology_snapshot": "Ontology snapshot belongs to another organization."})
        if gates.ontology_snapshot and snapshot_organization_id is None:
            raise ValidationError({"ontology_snapshot": "Complete ontology snapshot requires an organization."})
        explanation = _json_copy(payload.get("explanation", {}), "explanation")
        LeadService._validate_explanation(explanation, evidence_ids=set(evidence_ids))
        extracted_values = _json_copy(
            payload.get("extracted_requirement_values", []), "extracted_requirement_values"
        )
        confidence = payload.get("confidence", {})
        if not isinstance(confidence, dict):
            raise ValidationError({"confidence": "Confidence must be an object."})

        requirements = payload.get("requirements", [])
        if not isinstance(requirements, list):
            raise ValidationError({"requirements": "Requirements must be a list."})
        prepared_requirements = LeadService._prepare_requirements(
            requirements,
            evidence_by_id={item.pk: item for item in locked_evidence},
            organization_id=locked_candidate.organization_id,
            frozen_snapshot=(frozen_ontology_snapshot if audited_output is not None else None),
            capability_bindings=(
                run.input_snapshot.get("capability_bindings", [])
                if audited_output is not None
                else None
            ),
        )
        if gates.capability_evidence and not any(
            row["capability_concept"] is not None
            and row["capability_knowledge_evidence"] is not None
            for row in prepared_requirements
        ):
            raise ValidationError(
                {"gates": "Capability-evidence gate requires an approved capability evidence link."}
            )
        if gates.ontology_snapshot:
            LeadService._validate_snapshot_links(
                snapshot=snapshot, requirements=prepared_requirements
            )

        latest_version = (
            LeadInsight.objects.filter(candidate=locked_candidate)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        frozen_reference_context = (
            lead_frozen_reference_writes(
                organization_id=locked_candidate.organization_id,
                ontology_snapshot=frozen_ontology_snapshot,
                capability_bindings=run.input_snapshot.get("capability_bindings", []),
            )
            if audited_output is not None
            else nullcontext()
        )
        with lead_history_writes(), frozen_reference_context:
            insight = LeadInsight.objects.create(
                organization=locked_candidate.organization,
                candidate=locked_candidate,
                ai_run=run,
                version=(latest_version or 0) + 1,
                intent_score=dimensions.intent,
                company_fit_score=dimensions.company_fit,
                specificity_score=dimensions.specificity,
                capability_fit_score=dimensions.capability_fit,
                recency_score=dimensions.recency,
                score=scored.total,
                score_band=scored.band,
                high_value_eligible=scored.high_value_eligible,
                traceable_source=gates.traceable_source,
                explicit_need_or_company_match=gates.explicit_need_or_company_match,
                capability_evidence=gates.capability_evidence,
                audited_run=gates.audited_run,
                ontology_snapshot_complete=gates.ontology_snapshot,
                explanation=explanation,
                extracted_requirement_values=extracted_values,
                evidence_confidence=_confidence(confidence.get("evidence"), "evidence_confidence"),
                company_match_confidence=_confidence(
                    confidence.get("company_match"), "company_match_confidence"
                ),
                ai_confidence=_confidence(confidence.get("ai"), "ai_confidence"),
                ontology_snapshot=snapshot,
            )
            for item in locked_evidence:
                LeadCandidateEvidence.objects.create(
                    organization=locked_candidate.organization,
                    candidate=locked_candidate,
                    insight=insight,
                    evidence=item,
                    source_signal=item.source_signal,
                )
            for row in prepared_requirements:
                LeadInsightRequirement.objects.create(
                    organization=locked_candidate.organization,
                    insight=insight,
                    **row,
                )

        locked_candidate.latest_insight = insight
        if locked_candidate.status == LeadCandidate.Status.ANALYZING:
            locked_candidate.status = LeadCandidate.Status.ANALYZED
        update_fields = ["latest_insight", "status", "updated_at"]
        lease_context = nullcontext()
        if locked_candidate.analysis_lease_token is not None:
            locked_candidate.analysis_lease_token = None
            update_fields.append("analysis_lease_token")
            lease_context = lead_analysis_lease_writes()
        with lease_context:
            locked_candidate.save(update_fields=update_fields)
        if isinstance(candidate, LeadCandidate):
            candidate.latest_insight = insight
            candidate.status = locked_candidate.status
            candidate.version = locked_candidate.version
            candidate.updated_at = locked_candidate.updated_at
        return insight

    @staticmethod
    @transaction.atomic
    def record_analysis_output(*, run, output):
        """Persist one strict provider result against the run's frozen references."""
        from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence

        frozen = run.input_snapshot
        candidate = LeadCandidate.objects.get(
            pk=frozen["lead_candidate_id"],
            organization_id=frozen["organization_id"],
        )
        evidence_ids = [row["id"] for row in frozen["evidence"]]
        evidence = list(
            SourceEvidence.objects.filter(
                pk__in=evidence_ids,
                organization=candidate.organization,
            ).order_by("pk")
        )
        evidence_by_id = {str(row.id): row for row in evidence}
        concepts_by_identity = {
            (row["concept_type"], row["code"]): row
            for row in frozen["ontology_snapshot"]["concept_versions"]
        }
        concept_ids = [row["concept_id"] for row in concepts_by_identity.values()]
        current_concepts = {
            str(row.id): row for row in KnowledgeConcept.objects.filter(pk__in=concept_ids)
        }
        binding_by_code = {
            row["capability_code"]: row
            for row in frozen.get("capability_bindings", [])
        }
        knowledge_ids = {
            item
            for row in binding_by_code.values()
            for item in row["knowledge_evidence_ids"]
        }
        knowledge_by_id = {
            str(row.id): row for row in KnowledgeEvidence.objects.filter(pk__in=knowledge_ids)
        }
        matches_by_source: dict[str, list[dict]] = {}
        for match in output["capability_matches"]:
            for source_evidence_id in match["source_evidence_ids"]:
                matches_by_source.setdefault(source_evidence_id, []).append(match)

        requirements_by_key = {}
        for extracted in output["requirements"]:
            frozen_requirement = concepts_by_identity[
                ("REQUIREMENT", extracted["type"])
            ]
            requirement_concept = current_concepts[frozen_requirement["concept_id"]]
            for source_evidence_id in extracted["evidence_ids"]:
                matches = sorted(
                    matches_by_source.get(source_evidence_id, []),
                    key=lambda row: (
                        row["capability_code"],
                        tuple(row["knowledge_evidence_ids"]),
                    ),
                )
                match = matches[0] if matches else None
                capability_concept = None
                capability_knowledge_evidence = None
                if match is not None:
                    frozen_capability = concepts_by_identity[
                        ("CAPABILITY", match["capability_code"])
                    ]
                    capability_concept = current_concepts[frozen_capability["concept_id"]]
                    capability_knowledge_evidence = knowledge_by_id[
                        match["knowledge_evidence_ids"][0]
                    ]
                key = (
                    str(requirement_concept.id),
                    source_evidence_id,
                    extracted["value"],
                    extracted["unit"],
                )
                requirements_by_key.setdefault(
                    key,
                    {
                        "requirement_concept": requirement_concept,
                        "capability_concept": capability_concept,
                        "capability_knowledge_evidence": capability_knowledge_evidence,
                        "extracted_value": extracted["value"],
                        "unit": extracted["unit"],
                        "evidence": evidence_by_id[source_evidence_id],
                    },
                )
        requirements = list(requirements_by_key.values())
        has_capability_evidence = any(
            row["capability_concept"] is not None
            and row["capability_knowledge_evidence"] is not None
            for row in requirements
        )
        payload = {
            "dimensions": output["dimensions"],
            "gates": {
                "traceable_source": bool(evidence),
                "explicit_need_or_company_match": not output["insufficient_evidence"],
                "capability_evidence": has_capability_evidence,
                "audited_run": True,
                "ontology_snapshot": True,
            },
            "explanation": {
                "company_name": output["company_name"],
                "company_domain": output.get("company_domain", ""),
                "country_hint": output.get("country_hint", ""),
                "need_summary_zh": output["need_summary_zh"],
                "need_summary_en": output["need_summary_en"],
                "insufficient_evidence": output["insufficient_evidence"],
                "reasons": output["reasons"],
            },
            "extracted_requirement_values": [
                {
                    "type": row["type"],
                    "value": row["value"],
                    "unit": row["unit"],
                    "evidence_ids": row["evidence_ids"],
                }
                for row in output["requirements"]
            ],
            "confidence": {
                "evidence": output["confidence"]["intent"],
                "company_match": output["confidence"]["company_fit"],
                "ai": output["confidence"]["capability"],
            },
            "ontology_snapshot": frozen["ontology_snapshot"],
            "requirements": requirements,
        }
        return LeadService.record_insight(
            organization=candidate.organization,
            candidate=candidate,
            ai_run=run,
            evidence=evidence,
            payload=payload,
            audited_output=output,
        )

    @staticmethod
    @transaction.atomic
    def recover_failed_analysis(
        *, organization_id, candidate_id, started_from, analysis_lease_token
    ):
        candidate = LeadCandidate.objects.select_for_update().filter(
            pk=candidate_id,
            organization_id=organization_id,
        ).first()
        if (
            candidate is None
            or not analysis_lease_token
            or str(candidate.analysis_lease_token) != str(analysis_lease_token)
        ):
            return
        if candidate.status != LeadCandidate.Status.ANALYZING:
            return
        if started_from == LeadCandidate.Status.DISCOVERED:
            candidate.status = LeadCandidate.Status.DISCOVERED
        elif started_from == LeadCandidate.Status.ANALYZED:
            candidate.status = LeadCandidate.Status.ANALYZED
        else:
            return
        candidate.analysis_lease_token = None
        with lead_analysis_lease_writes():
            candidate.save(
                update_fields=["status", "analysis_lease_token", "updated_at"]
            )

    @staticmethod
    @transaction.atomic
    def resume_analysis_retry(
        *, organization_id, candidate_id, started_from, analysis_lease_token
    ):
        if not analysis_lease_token:
            raise LeadStateError("Frozen analysis lease is required for retry.")
        candidate = LeadCandidate.objects.select_for_update().filter(
            pk=candidate_id,
            organization_id=organization_id,
        ).first()
        if candidate is None:
            raise LeadStateError("Lead candidate is unavailable for retry.")
        if str(candidate.analysis_lease_token) == str(analysis_lease_token):
            return candidate
        if candidate.analysis_lease_token is not None:
            raise LeadStateError("Lead candidate is owned by another analysis.")
        expected_status = (
            LeadCandidate.Status.DISCOVERED
            if started_from == LeadCandidate.Status.DISCOVERED
            else LeadCandidate.Status.ANALYZED
        )
        if candidate.status != expected_status:
            raise LeadStateError("Lead candidate is not recoverable for retry.")
        candidate.status = LeadCandidate.Status.ANALYZING
        candidate.analysis_lease_token = analysis_lease_token
        with lead_analysis_lease_writes():
            candidate.save(
                update_fields=["status", "analysis_lease_token", "updated_at"]
            )
        return candidate

    @staticmethod
    def _validate_explanation(explanation, *, evidence_ids):
        if not isinstance(explanation, dict):
            raise ValidationError({"explanation": "Explanation must be an object."})
        reasons = explanation.get("reasons", [])
        if not isinstance(reasons, list):
            raise ValidationError({"explanation": "Explanation reasons must be a list."})
        known = {str(item) for item in evidence_ids}
        for reason in reasons:
            references = reason.get("evidence_ids") if isinstance(reason, dict) else None
            if not isinstance(references, list) or not references or not set(map(str, references)) <= known:
                raise ValidationError(
                    {"explanation": "Every explanation reason must reference linked evidence."}
                )

    @staticmethod
    def _validate_frozen_analysis_binding(*, run, candidate, evidence):
        from apps.knowledge.services import validate_frozen_ontology_snapshot
        from apps.sources.services import canonical_source_evidence_snapshot

        from .schemas import frozen_source_evidence_errors

        frozen = run.input_snapshot
        bound = run.job.input_snapshot
        input_is_bound = isinstance(frozen, dict) and bound == frozen
        if isinstance(frozen, dict) and run.job_attempt > 1:
            expected = json.loads(json.dumps(bound))
            expected["analysis_lease_id"] = str(
                lead_analysis_attempt_lease(run.job_id, run.job_attempt)
            )
            retry_version = frozen.get("analysis_lease_version")
            expected["analysis_lease_version"] = retry_version
            expected["integrity_sha256"] = frozen.get("integrity_sha256")
            input_is_bound = (
                isinstance(retry_version, int)
                and not isinstance(retry_version, bool)
                and retry_version > bound.get("analysis_lease_version", 0)
                and expected == frozen
            )
        if not input_is_bound:
            raise ValidationError({"ai_run": "AI run is not bound to its immutable job input."})
        if (
            frozen.get("organization_id") != str(candidate.organization_id)
            or frozen.get("lead_candidate_id") != str(candidate.id)
        ):
            raise ValidationError({"ai_run": "AI run is bound to another candidate."})
        rows = frozen.get("evidence")
        if frozen_source_evidence_errors(
            rows,
            organization_id=candidate.organization_id,
        ):
            raise ValidationError({"ai_run": "AI run evidence snapshot is invalid."})
        if [row["id"] for row in rows] != [str(item.id) for item in evidence]:
            raise ValidationError({"ai_run": "AI run is bound to another evidence set."})
        supplied_digest = frozen.get("integrity_sha256")
        if supplied_digest is not None:
            digest_input = dict(frozen)
            digest_input.pop("integrity_sha256", None)
            encoded = json.dumps(
                digest_input,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected_digest = hashlib.sha256(encoded).hexdigest()
            if not isinstance(supplied_digest, str) or not hmac.compare_digest(
                supplied_digest, expected_digest
            ):
                raise ValidationError({"ai_run": "AI run input integrity is invalid."})
        else:
            expected_rows = [
                canonical_source_evidence_snapshot(
                    item,
                    organization=candidate.organization,
                )
                for item in evidence
            ]
            if rows != expected_rows:
                raise ValidationError({"ai_run": "AI run evidence snapshot is invalid."})
        ontology = frozen.get("ontology_snapshot")
        try:
            ontology = validate_frozen_ontology_snapshot(
                ontology,
                organization_id=candidate.organization_id,
            )
        except ValidationError as error:
            raise ValidationError({"ai_run": "AI run ontology snapshot is invalid."}) from error
        return ontology

    @staticmethod
    def _prepare_requirements(
        requirements,
        *,
        evidence_by_id,
        organization_id,
        frozen_snapshot=None,
        capability_bindings=None,
    ):
        from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeStatus

        prepared = []
        frozen_concepts = {
            str(row["concept_id"]): row
            for row in (frozen_snapshot or {}).get("concept_versions", [])
            if isinstance(row, dict) and row.get("concept_id")
        }
        frozen_capability_evidence = {
            str(row["capability_concept_id"]): {
                str(item) for item in row.get("knowledge_evidence_ids", [])
            }
            for row in capability_bindings or []
            if isinstance(row, dict) and row.get("capability_concept_id")
        }
        use_frozen_references = frozen_snapshot is not None
        for row in requirements:
            if not isinstance(row, dict):
                raise ValidationError({"requirements": "Each requirement must be an object."})
            supplied_requirement = row.get("requirement_concept")
            supplied_capability = row.get("capability_concept")
            supplied_knowledge_evidence = row.get("capability_knowledge_evidence")
            evidence = row.get("evidence")
            if not isinstance(supplied_requirement, KnowledgeConcept):
                raise ValidationError({"requirements": "Requirement concept is invalid."})
            requirement = KnowledgeConcept.objects.filter(pk=supplied_requirement.pk).first()
            capability = None
            capability_knowledge_evidence = None
            if supplied_capability is not None:
                if not isinstance(supplied_capability, KnowledgeConcept):
                    raise ValidationError({"requirements": "Capability concept is invalid."})
                capability = KnowledgeConcept.objects.filter(pk=supplied_capability.pk).first()
            if supplied_knowledge_evidence is not None:
                if not isinstance(supplied_knowledge_evidence, KnowledgeEvidence):
                    raise ValidationError({"requirements": "Capability knowledge evidence is invalid."})
                capability_knowledge_evidence = KnowledgeEvidence.objects.filter(
                    pk=supplied_knowledge_evidence.pk
                ).first()
            if requirement is None:
                raise ValidationError({"requirements": "Requirement concept is invalid."})
            frozen_requirement = frozen_concepts.get(str(requirement.id))
            requirement_is_valid = (
                frozen_requirement is not None
                and frozen_requirement.get("status") == KnowledgeStatus.APPROVED
                and frozen_requirement.get("concept_type")
                == KnowledgeConcept.ConceptType.REQUIREMENT
            ) if use_frozen_references else (
                requirement.status == KnowledgeStatus.APPROVED
                and requirement.concept_type == KnowledgeConcept.ConceptType.REQUIREMENT
                and requirement.organization_id in {None, organization_id}
            )
            if not requirement_is_valid:
                raise ValidationError({"requirements": "Requirement concept is not approved or visible."})
            if supplied_capability is not None and capability is None:
                raise ValidationError({"requirements": "Capability concept is invalid."})
            frozen_capability = (
                frozen_concepts.get(str(capability.id)) if capability is not None else None
            )
            capability_is_valid = capability is None or (
                frozen_capability is not None
                and frozen_capability.get("status") == KnowledgeStatus.APPROVED
                and frozen_capability.get("concept_type")
                == KnowledgeConcept.ConceptType.CAPABILITY
            ) if use_frozen_references else capability is None or (
                capability.status == KnowledgeStatus.APPROVED
                and capability.concept_type == KnowledgeConcept.ConceptType.CAPABILITY
                and capability.organization_id in {None, organization_id}
            )
            if not capability_is_valid:
                raise ValidationError({"requirements": "Capability concept is not approved or visible."})
            if supplied_knowledge_evidence is not None and capability_knowledge_evidence is None:
                raise ValidationError({"requirements": "Capability knowledge evidence is invalid."})
            frozen_evidence_is_valid = (
                capability is not None
                and str(capability_knowledge_evidence.id)
                in frozen_capability_evidence.get(str(capability.id), set())
            ) if capability_knowledge_evidence is not None else True
            current_evidence_is_valid = (
                capability is not None
                and capability_knowledge_evidence.status == KnowledgeStatus.APPROVED
                and capability_knowledge_evidence.organization_id in {None, organization_id}
                and capability.evidence.filter(pk=capability_knowledge_evidence.pk).exists()
            ) if capability_knowledge_evidence is not None else True
            if capability_knowledge_evidence is not None and not (
                frozen_evidence_is_valid if use_frozen_references else current_evidence_is_valid
            ):
                raise ValidationError(
                    {"requirements": "Capability knowledge evidence is not approved, visible, and linked."}
                )
            if not isinstance(evidence, SourceEvidence) or evidence.pk not in evidence_by_id:
                raise ValidationError({"requirements": "Requirement evidence is not linked to this insight."})
            prepared.append(
                {
                    "requirement_concept": requirement,
                    "capability_concept": capability,
                    "capability_knowledge_evidence": capability_knowledge_evidence,
                    "source_evidence": evidence_by_id[evidence.pk],
                    "extracted_value": str(row.get("extracted_value", "")).strip(),
                    "unit": str(row.get("unit", "")).strip(),
                }
            )
        return prepared

    @staticmethod
    def _validate_snapshot_links(*, snapshot, requirements):
        concept_ids = {str(item) for item in snapshot.get("concept_ids", [])}
        evidence_ids = {str(item) for item in snapshot.get("evidence_ids", [])}
        for row in snapshot.get("concept_versions", []):
            if isinstance(row, dict) and row.get("concept_id"):
                concept_ids.add(str(row["concept_id"]))
        for row in snapshot.get("evidence_references", []):
            if isinstance(row, dict) and row.get("evidence_id"):
                evidence_ids.add(str(row["evidence_id"]))
        required_concepts = {
            str(concept.id)
            for row in requirements
            for concept in (row["requirement_concept"], row["capability_concept"])
            if concept is not None
        }
        required_evidence = {
            str(row["capability_knowledge_evidence"].id)
            for row in requirements
            if row["capability_knowledge_evidence"] is not None
        }
        if not required_concepts <= concept_ids or not required_evidence <= evidence_ids:
            raise ValidationError(
                {"ontology_snapshot": "Ontology snapshot must include every linked concept and evidence record."}
            )


class LeadAnalysisService:
    @staticmethod
    def _refresh_snapshot_digest(snapshot):
        snapshot = dict(snapshot)
        snapshot.pop("integrity_sha256", None)
        encoded = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        snapshot["integrity_sha256"] = hashlib.sha256(encoded).hexdigest()
        return snapshot

    @staticmethod
    def _routing_signals(*, candidate, snapshot) -> dict[str, object]:
        codes = []
        quantities = set()
        conflict_language = False
        for row in snapshot.get("evidence", []):
            text = row.get("original_text", "") if isinstance(row, dict) else ""
            lowered = text.lower()
            quantities.update(re.findall(r"\b\d+(?:\.\d+)?\s*(?:pcs|pieces|units)\b", lowered))
            conflict_language = conflict_language or any(
                marker in lowered
                for marker in ("correction:", "instead of", "not ", "actually ", "rather than")
            )
        if len(quantities) > 1 and conflict_language:
            codes.append("CONFLICTING_QUANTITIES")
        latest = candidate.latest_insight
        if latest is not None and min(
            latest.evidence_confidence,
            latest.company_match_confidence,
            latest.ai_confidence,
        ) < Decimal("0.6500"):
            codes.append("LOW_TRUSTED_CONFIDENCE")
        return {"codes": sorted(codes), "policy_version": 1}

    @staticmethod
    def _matches_existing(
        job, binding, *, candidate_id, evidence_ids, expected_version,
        administrator_override,
    ):
        snapshot = job.input_snapshot
        routing = snapshot.get("ai_routing", {}) if isinstance(snapshot, dict) else {}
        return (
            binding is not None
            and str(binding.candidate_id) == str(candidate_id)
            and isinstance(snapshot, dict)
            and snapshot.get("lead_candidate_id") == str(candidate_id)
            and snapshot.get("analysis_lease_version") == expected_version + 1
            and sorted(row.get("id") for row in snapshot.get("evidence", []))
            == sorted(str(item) for item in evidence_ids)
            and bool(routing.get("override_reason")) == bool(administrator_override)
        )

    @staticmethod
    @transaction.atomic
    def schedule(
        *, organization, candidate, evidence_ids, expected_version, idempotency_key, actor,
        administrator_override=False,
    ):
        from .tasks import execute_lead_analysis
        from apps.identity.services import lock_organization_scope

        organization = lock_organization_scope(organization=organization)

        candidate_id = getattr(candidate, "pk", candidate)
        locked = LeadCandidate.objects.select_for_update().filter(
            pk=candidate_id, organization=organization
        ).first()
        if locked is None:
            raise ValidationError(
                {"candidate": "Lead candidate is unavailable for this organization."}
            )
        requested_ids = [getattr(item, "pk", item) for item in evidence_ids]
        existing = Job.objects.filter(
            organization=organization,
            type=Job.Type.LEAD_ANALYZE,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            binding = LeadAnalysisBinding.objects.select_related("prompt_version").filter(
                job=existing, organization=organization
            ).first()
            if not LeadAnalysisService._matches_existing(
                existing,
                binding,
                candidate_id=candidate_id,
                evidence_ids=requested_ids,
                expected_version=expected_version,
                administrator_override=administrator_override,
            ):
                raise LeadIdempotencyConflictError(
                    "Idempotency key already has a different lead-analysis request."
                )
            return existing, binding.prompt_version

        if locked.version != expected_version:
            raise LeadVersionConflict("Lead candidate version is stale.")
        prompt = PromptVersion.objects.filter(
            purpose="LEAD_ANALYZE", status=PromptVersion.Status.PUBLISHED
        ).order_by("-version", "-id").first()
        if prompt is None:
            raise LeadStateError("Published lead-analysis prompt is unavailable.")
        from .schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA

        if prompt.output_schema != LEAD_ANALYSIS_OUTPUT_SCHEMA:
            raise LeadStateError(
                "Published lead-analysis prompt has an incompatible output schema."
            )
        snapshot = build_analysis_snapshot(
            candidate=locked,
            evidence_ids=requested_ids,
            actor=actor,
        )
        snapshot = {
            **snapshot,
            "routing_signals": LeadAnalysisService._routing_signals(
                candidate=locked, snapshot=snapshot
            ),
        }
        snapshot = LeadAnalysisService._refresh_snapshot_digest(snapshot)
        decision = None
        if prompt.provider == "deepseek":
            from apps.ai.routing import build_provider_input, route_ai_work, routing_snapshot
            from .orchestration import _render_lead_prompt

            decision = route_ai_work(
                job_type=Job.Type.LEAD_ANALYZE,
                snapshot=snapshot,
                administrator_override=administrator_override,
                actor=actor,
            )
            snapshot = {**snapshot, "ai_routing": routing_snapshot(decision)}
            snapshot = LeadAnalysisService._refresh_snapshot_digest(snapshot)
            decision = route_ai_work(
                job_type=Job.Type.LEAD_ANALYZE,
                snapshot=snapshot,
                administrator_override=administrator_override,
                actor=actor,
                provider_input=build_provider_input(
                    prompt=_render_lead_prompt(prompt.template, snapshot),
                    schema=prompt.output_schema,
                    snapshot=snapshot,
                ),
            )
        try:
            job = JobService.create(
                organization=organization,
                job_type=Job.Type.LEAD_ANALYZE,
                input_snapshot=snapshot,
                idempotency_key=idempotency_key,
                created_by=actor,
            )
        except JobConflictError as error:
            raise LeadIdempotencyConflictError(str(error)) from error
        if not getattr(job, "_service_created", False):
            raise LeadIdempotencyConflictError(
                "Idempotency key already has a different lead-analysis request."
            )
        if decision is not None:
            from apps.ai.routing import create_execution_intent

            create_execution_intent(
                job=job, decision=decision, created_by=actor,
                provider_prompt=_render_lead_prompt(prompt.template, snapshot),
                provider_schema=prompt.output_schema,
                prompt_purpose=prompt.purpose,
                prompt_version_id=prompt.id,
            )
        with lead_history_writes():
            LeadAnalysisBinding.objects.create(
                organization=organization,
                job=job,
                candidate=locked,
                prompt_version=prompt,
                requested_by=actor,
            )
        transaction.on_commit(
            lambda: execute_lead_analysis.delay(str(job.id), str(prompt.id))
        )
        return job, prompt


class LeadReviewService:
    _DIMENSIONS = {
        "intent": ("intent_score", 30),
        "company_fit": ("company_fit_score", 25),
        "specificity": ("specificity_score", 20),
        "capability_fit": ("capability_fit_score", 15),
        "recency": ("recency_score", 10),
    }
    _GATES = {
        "traceable_source": "traceable_source",
        "explicit_need_or_company_match": "explicit_need_or_company_match",
        "capability_evidence": "capability_evidence",
        "audited_run": "audited_run",
        "ontology_snapshot": "ontology_snapshot_complete",
    }
    _COMPANY_FIELDS = frozenset({"company_name", "company_domain", "country_hint"})

    @staticmethod
    def _canonical_intent(*, candidate_id, action, expected_version, correction, reason):
        payload = {
            "candidate_id": str(candidate_id),
            "action": action,
            "expected_version": expected_version,
            "correction": scrub_secrets(correction),
            "reason": " ".join(reason.strip().split()),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return payload, hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_correction(correction):
        if not isinstance(correction, dict) or not correction:
            raise ValidationError({"correction": "A non-empty correction is required."})
        allowed = LeadReviewService._COMPANY_FIELDS | {
            "dimension_overrides",
            "gate_overrides",
        }
        unknown = set(correction) - allowed
        if unknown:
            raise ValidationError(
                {"correction": f"Unknown correction fields: {', '.join(sorted(unknown))}."}
            )
        dimensions = correction.get("dimension_overrides", {})
        gates = correction.get("gate_overrides", {})
        if not isinstance(dimensions, dict) or set(dimensions) - set(
            LeadReviewService._DIMENSIONS
        ):
            raise ValidationError({"correction": "Dimension overrides are invalid."})
        reviewer_gate_overrides = {"explicit_need_or_company_match"}
        if not isinstance(gates, dict) or set(gates) - reviewer_gate_overrides:
            raise ValidationError({"correction": "Gate overrides are invalid."})
        for name, value in dimensions.items():
            maximum = LeadReviewService._DIMENSIONS[name][1]
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
                raise ValidationError(
                    {"correction": f"{name} must be between 0 and {maximum}."}
                )
        if any(not isinstance(value, bool) for value in gates.values()):
            raise ValidationError({"correction": "Gate overrides must be booleans."})
        cleaned = _json_copy(scrub_secrets(correction), "correction")
        if len(json.dumps(cleaned, ensure_ascii=False)) > 16_000:
            raise ValidationError({"correction": "Correction is too large."})
        return cleaned

    @staticmethod
    def _corrected_insight(*, candidate, original, correction, reviewer, reason):
        dimensions = {
            name: getattr(original, field)
            for name, (field, _maximum) in LeadReviewService._DIMENSIONS.items()
        }
        dimensions.update(correction.get("dimension_overrides", {}))
        gates = {
            name: getattr(original, field)
            for name, field in LeadReviewService._GATES.items()
        }
        gates.update(correction.get("gate_overrides", {}))
        scored = score_lead(ScoreDimensions(**dimensions), EvidenceGates(**gates))
        now = timezone.now()
        latest_version = (
            LeadInsight.objects.filter(candidate=candidate)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        frozen_bindings = original.ai_run.input_snapshot.get("capability_bindings")
        frozen_context = (
            lead_frozen_reference_writes(
                organization_id=candidate.organization_id,
                ontology_snapshot=original.ontology_snapshot,
                capability_bindings=frozen_bindings,
            )
            if isinstance(frozen_bindings, list)
            else nullcontext()
        )
        with lead_history_writes(), frozen_context:
            insight = LeadInsight.objects.create(
                organization=candidate.organization,
                candidate=candidate,
                ai_run=original.ai_run,
                origin=LeadInsight.Origin.HUMAN_CORRECTION,
                source_insight=original,
                human_correction=correction,
                reviewed_by=reviewer,
                reviewed_at=now,
                review_reason=reason,
                version=(latest_version or 0) + 1,
                intent_score=dimensions["intent"],
                company_fit_score=dimensions["company_fit"],
                specificity_score=dimensions["specificity"],
                capability_fit_score=dimensions["capability_fit"],
                recency_score=dimensions["recency"],
                score=scored.total,
                score_band=scored.band,
                high_value_eligible=scored.high_value_eligible,
                traceable_source=gates["traceable_source"],
                explicit_need_or_company_match=gates[
                    "explicit_need_or_company_match"
                ],
                capability_evidence=gates["capability_evidence"],
                audited_run=gates["audited_run"],
                ontology_snapshot_complete=gates["ontology_snapshot"],
                explanation=_json_copy(original.explanation, "explanation"),
                extracted_requirement_values=_json_copy(
                    original.extracted_requirement_values,
                    "extracted_requirement_values",
                ),
                evidence_confidence=original.evidence_confidence,
                company_match_confidence=original.company_match_confidence,
                ai_confidence=original.ai_confidence,
                ontology_snapshot=_json_copy(
                    original.ontology_snapshot, "ontology_snapshot"
                ),
            )
            for link in original.evidence_links.select_related(
                "evidence", "source_signal"
            ):
                LeadCandidateEvidence.objects.create(
                    organization=candidate.organization,
                    candidate=candidate,
                    insight=insight,
                    evidence=link.evidence,
                    source_signal=link.source_signal,
                )
            for requirement in original.requirements.select_related(
                "requirement_concept",
                "capability_concept",
                "capability_knowledge_evidence",
                "source_evidence",
            ):
                LeadInsightRequirement.objects.create(
                    organization=candidate.organization,
                    insight=insight,
                    requirement_concept=requirement.requirement_concept,
                    capability_concept=requirement.capability_concept,
                    capability_knowledge_evidence=(
                        requirement.capability_knowledge_evidence
                    ),
                    source_evidence=requirement.source_evidence,
                    extracted_value=requirement.extracted_value,
                    unit=requirement.unit,
                )
        return insight

    @staticmethod
    @transaction.atomic
    def apply(
        *,
        organization,
        candidate,
        action,
        expected_version,
        reason,
        reviewer,
        idempotency_key,
        correction=None,
    ):
        from apps.identity.models import Membership
        from apps.identity.permissions import PermissionCode
        from apps.identity.services import get_active_membership, require_permission

        try:
            membership = get_active_membership(user=reviewer)
        except Membership.DoesNotExist as error:
            raise PermissionDenied(
                "An active review membership is required."
            ) from error
        if membership.organization_id != organization.id:
            raise PermissionDenied("An active review membership is required.")
        require_permission(
            membership=membership,
            permission=PermissionCode.LEADS_REVIEW,
        )
        if action in {"MERGE_COMPANY", "SPLIT_COMPANY"}:
            raise ValidationError({"action": "This review action is reserved for B2."})
        if action not in LeadReview.Action.values:
            raise ValidationError({"action": "Unsupported B1 review action."})
        normalized_reason = " ".join(str(reason).strip().split())
        if not normalized_reason or len(normalized_reason) > 2000:
            raise ValidationError({"reason": "Provide a reason up to 2000 characters."})
        candidate_id = getattr(candidate, "pk", candidate)
        intent, intent_hash = LeadReviewService._canonical_intent(
            candidate_id=candidate_id,
            action=action,
            expected_version=expected_version,
            correction=correction,
            reason=normalized_reason,
        )
        existing = LeadReview.objects.select_related("candidate", "insight").filter(
            organization=organization,
            reviewer=reviewer,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if not hmac.compare_digest(existing.intent_hash, intent_hash):
                raise LeadIdempotencyConflictError(
                    "Idempotency key already has a different review intent."
                )
            return LeadReviewResult(existing, existing.candidate, existing.insight)

        locked = LeadCandidate.objects.select_for_update().filter(
            pk=candidate_id, organization=organization
        ).first()
        if locked is None:
            raise ValidationError(
                {"candidate": "Lead candidate is unavailable for this organization."}
            )
        if locked.version != expected_version:
            raise LeadVersionConflict("Lead candidate version is stale.")
        if locked.analysis_lease_token is not None:
            raise LeadStateError(
                "Lead candidate has an active analysis lease; manual review is disabled."
            )

        insight = locked.latest_insight
        normalized_correction = None
        ignore_fingerprint = ""
        if action == LeadReview.Action.CORRECT:
            if locked.status != LeadCandidate.Status.ANALYZED or insight is None:
                raise LeadStateError("Only analyzed candidates can be corrected.")
            normalized_correction = LeadReviewService._validate_correction(correction)
            insight = LeadReviewService._corrected_insight(
                candidate=locked,
                original=insight,
                correction=normalized_correction,
                reviewer=reviewer,
                reason=normalized_reason,
            )
            for field in LeadReviewService._COMPANY_FIELDS:
                if field in normalized_correction:
                    setattr(locked, field, str(normalized_correction[field]).strip())
            locked.latest_insight = insight
            locked.status = LeadCandidate.Status.REVIEWED
        elif action == LeadReview.Action.CONFIRM:
            if locked.status != LeadCandidate.Status.ANALYZED or insight is None:
                raise LeadStateError("Only analyzed candidates can be confirmed.")
            locked.status = LeadCandidate.Status.REVIEWED
        elif action == LeadReview.Action.DISMISS:
            if locked.status not in {
                LeadCandidate.Status.ANALYZED,
                LeadCandidate.Status.REVIEWED,
            }:
                raise LeadStateError("Only analyzed or reviewed candidates can be dismissed.")
            if not (locked.company_domain or locked.company_name).strip():
                raise LeadStateError(
                    "Lead candidate requires an enterprise identity before dismissal."
                )
            locked.status = LeadCandidate.Status.DISMISSED
            identity = (locked.company_domain or locked.company_name).strip().casefold()
            ignore_fingerprint = hashlib.sha256(
                f"{organization.id}:{identity}".encode()
            ).hexdigest()
        elif action == LeadReview.Action.REOPEN:
            if locked.status != LeadCandidate.Status.DISMISSED:
                raise LeadStateError("Only dismissed candidates can be reopened.")
            locked.status = LeadCandidate.Status.DISCOVERED
        else:
            if locked.status not in {
                LeadCandidate.Status.ANALYZED,
                LeadCandidate.Status.REVIEWED,
            }:
                raise LeadStateError(
                    "More evidence can be requested only after analysis or review."
                )

        locked.save(
            update_fields=[
                "company_name",
                "company_domain",
                "country_hint",
                "latest_insight",
                "status",
                "updated_at",
            ]
        )
        if action in {LeadReview.Action.CONFIRM, LeadReview.Action.CORRECT}:
            linked_ids = set(
                locked.evidence_links.values_list("evidence_id", flat=True)
            )
            if linked_ids:
                EvidenceService.protect_confirmed(
                    organization=organization, evidence_ids=linked_ids
                )
        try:
            with transaction.atomic(), lead_history_writes():
                review = LeadReview.objects.create(
                    organization=organization,
                    candidate=locked,
                    insight=insight,
                    action=action,
                    reason=normalized_reason,
                    correction=normalized_correction,
                    reviewer=reviewer,
                    idempotency_key=idempotency_key,
                    intent_hash=intent_hash,
                    ignore_fingerprint=ignore_fingerprint,
                    candidate_status=locked.status,
                    candidate_version=locked.version,
                )
        except IntegrityError as error:
            raise LeadIdempotencyConflictError(
                "Idempotency key was used concurrently for another review."
            ) from error
        return LeadReviewResult(review, locked, insight)


__all__ = [
    "LeadAnalysisService",
    "LeadIdempotencyConflictError",
    "LeadReviewResult",
    "LeadReviewService",
    "LeadService",
    "LeadStateError",
    "LeadVersionConflict",
    "build_analysis_snapshot",
    "canonical_lead_insight_output",
]


@transaction.atomic
def build_analysis_snapshot(*, candidate, evidence_ids, actor) -> dict[str, object]:
    """Freeze an authorized candidate, its linked evidence, and relevant ontology."""
    from django.core.exceptions import PermissionDenied

    from apps.identity.models import Membership
    from apps.identity.permissions import PermissionCode
    from apps.identity.services import get_active_membership, require_permission
    from apps.identity.services import lock_organization_scope
    from apps.knowledge.models import (
        KnowledgeConcept,
        KnowledgeConceptEvidence,
        KnowledgeStatus,
    )
    from apps.knowledge.services import build_frozen_snapshot
    from apps.sources.services import canonical_source_evidence_snapshot

    try:
        membership = get_active_membership(user=actor)
    except Membership.DoesNotExist as error:
        raise PermissionDenied("An active organization membership is required.") from error
    require_permission(membership=membership, permission=PermissionCode.LEADS_ANALYZE)
    organization = lock_organization_scope(
        organization=membership.organization
    )
    candidate_id = getattr(candidate, "pk", candidate)
    locked_candidate = (
        LeadCandidate.objects.select_for_update()
        .filter(pk=candidate_id, organization=organization)
        .first()
    )
    if locked_candidate is None:
        raise ValidationError({"candidate": "Lead candidate is unavailable for this organization."})

    requested_ids = [getattr(item, "pk", item) for item in evidence_ids]
    if not requested_ids or len(set(requested_ids)) != len(requested_ids):
        raise ValidationError({"evidence_ids": "Evidence IDs must be a non-empty unique list."})
    linked_ids = set(
        locked_candidate.evidence_links.values_list("evidence_id", flat=True)
    )
    if locked_candidate.source_signal_id:
        linked_ids.update(
            SourceEvidence.objects.filter(
                organization=organization,
                source_signal_id=locked_candidate.source_signal_id,
            ).values_list("id", flat=True)
        )
    if not set(requested_ids) <= linked_ids:
        raise ValidationError(
            {"evidence_ids": "Every evidence record must be linked to this candidate and organization."}
        )
    evidence_rows = list(
        SourceEvidence.objects.select_for_update()
        .filter(
            organization=organization,
            pk__in=requested_ids,
        )
        .order_by("pk")
    )
    if {row.pk for row in evidence_rows} != set(requested_ids):
        raise ValidationError(
            {"evidence_ids": "Every evidence record must be linked to this candidate and organization."}
        )
    if any(
        row.availability != SourceEvidence.Availability.AVAILABLE
        or not row.original_text.strip()
        for row in evidence_rows
    ):
        raise ValidationError(
            {
                "evidence_ids": (
                    "Lead analysis requires available non-empty original evidence."
                )
            }
        )

    visible = models.Q(organization__isnull=True) | models.Q(organization=organization)
    concept_ids = list(
        KnowledgeConcept.objects.filter(
            visible,
            status=KnowledgeStatus.APPROVED,
            concept_type__in=[
                KnowledgeConcept.ConceptType.REQUIREMENT,
                KnowledgeConcept.ConceptType.CAPABILITY,
            ],
        )
        .order_by("code", "id")
        .values_list("id", flat=True)
    )
    ontology_snapshot = build_frozen_snapshot(
        organization=organization,
        concept_ids=concept_ids,
    )
    seen_identities: dict[tuple[str, str], str] = {}
    for row in ontology_snapshot["concept_versions"]:
        identity = (row["concept_type"], row["code"])
        if identity in seen_identities:
            raise ValidationError(
                {
                    "ontology_snapshot": (
                        f"Ambiguous approved {row['concept_type']} code '{row['code']}'. "
                        "Rename or deprecate one visible definition before analysis."
                    )
                }
            )
        seen_identities[identity] = row["concept_id"]
    frozen_concept_ids = {
        row["concept_id"] for row in ontology_snapshot["concept_versions"]
    }
    frozen_evidence_ids = {
        row["evidence_id"] for row in ontology_snapshot["evidence_references"]
    }
    capability_rows = {
        row["concept_id"]: row
        for row in ontology_snapshot["concept_versions"]
        if row["concept_type"] == KnowledgeConcept.ConceptType.CAPABILITY
    }
    bindings_by_concept: dict[str, list[str]] = {
        concept_id: [] for concept_id in capability_rows
    }
    for concept_id, evidence_id in KnowledgeConceptEvidence.objects.filter(
        knowledgeconcept_id__in=frozen_concept_ids,
        knowledgeevidence_id__in=frozen_evidence_ids,
    ).values_list("knowledgeconcept_id", "knowledgeevidence_id"):
        key = str(concept_id)
        if key in bindings_by_concept:
            bindings_by_concept[key].append(str(evidence_id))
    capability_bindings = [
        {
            "capability_code": capability_rows[concept_id]["code"],
            "capability_concept_id": concept_id,
            "knowledge_evidence_ids": sorted(evidence_ids),
        }
        for concept_id, evidence_ids in sorted(
            bindings_by_concept.items(),
            key=lambda item: (capability_rows[item[0]]["code"], item[0]),
        )
    ]

    started_from = locked_candidate.status
    locked_candidate = LeadService.begin_analysis(
        organization=organization,
        candidate=locked_candidate,
        expected_version=locked_candidate.version,
    )

    snapshot = {
        "schema": "LEAD_ANALYSIS_INPUT_V1",
        "organization_id": str(organization.id),
        "lead_candidate_id": str(locked_candidate.id),
        "candidate_status_at_start": started_from,
        "analysis_lease_id": str(locked_candidate.analysis_lease_token),
        "analysis_lease_version": locked_candidate.version,
        "candidate": {
            "company_name": locked_candidate.company_name,
            "company_domain": locked_candidate.company_domain,
            "country_hint": locked_candidate.country_hint,
        },
        "evidence": [
            canonical_source_evidence_snapshot(row, organization=organization)
            for row in evidence_rows
        ],
        "ontology_snapshot": ontology_snapshot,
        "capability_bindings": capability_bindings,
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot["integrity_sha256"] = hashlib.sha256(encoded).hexdigest()
    return snapshot
