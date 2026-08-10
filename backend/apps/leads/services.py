import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.ai.models import AIRun
from apps.jobs.models import Job
from apps.sources.models import SourceEvidence

from .models import (
    LeadCandidate,
    LeadCandidateEvidence,
    LeadInsight,
    LeadInsightRequirement,
    LeadVersionConflict,
    lead_history_writes,
)
from .scoring import EvidenceGates, ScoreDimensions, score_lead


class LeadStateError(ValueError):
    pass


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
    def record_insight(*, organization, candidate, ai_run, evidence, payload):
        candidate_id = candidate.pk if isinstance(candidate, LeadCandidate) else candidate
        locked_candidate = LeadCandidate.objects.select_for_update().get(
            pk=candidate_id, organization=organization
        )
        if locked_candidate.status not in {
            LeadCandidate.Status.ANALYZING,
            LeadCandidate.Status.ANALYZED,
        }:
            raise LeadStateError("Lead must be analyzing or analyzed before recording insight.")
        run = AIRun.objects.select_related("job", "prompt_version").get(pk=ai_run.pk)
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
        if run.output_json != canonical_lead_insight_output(payload):
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
        with lead_history_writes():
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
        locked_candidate.save(update_fields=["latest_insight", "status", "updated_at"])
        if isinstance(candidate, LeadCandidate):
            candidate.latest_insight = insight
            candidate.status = locked_candidate.status
            candidate.version = locked_candidate.version
            candidate.updated_at = locked_candidate.updated_at
        return insight

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

        frozen = run.input_snapshot
        if not isinstance(frozen, dict) or run.job.input_snapshot != frozen:
            raise ValidationError({"ai_run": "AI run is not bound to its immutable job input."})
        if (
            frozen.get("organization_id") != str(candidate.organization_id)
            or frozen.get("lead_candidate_id") != str(candidate.id)
        ):
            raise ValidationError({"ai_run": "AI run is bound to another candidate."})
        rows = frozen.get("evidence")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValidationError({"ai_run": "AI run evidence snapshot is invalid."})
        expected_rows = [
            canonical_source_evidence_snapshot(
                item,
                organization=candidate.organization,
            )
            for item in evidence
        ]
        if rows != expected_rows:
            raise ValidationError({"ai_run": "AI run is bound to another evidence set."})
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
    def _prepare_requirements(requirements, *, evidence_by_id, organization_id):
        from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeStatus

        prepared = []
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
            if requirement.status != KnowledgeStatus.APPROVED or requirement.concept_type != (
                KnowledgeConcept.ConceptType.REQUIREMENT
            ) or requirement.organization_id not in {None, organization_id}:
                raise ValidationError({"requirements": "Requirement concept is not approved or visible."})
            if supplied_capability is not None and capability is None:
                raise ValidationError({"requirements": "Capability concept is invalid."})
            if capability is not None and (
                capability.status != KnowledgeStatus.APPROVED
                or capability.concept_type != KnowledgeConcept.ConceptType.CAPABILITY
                or capability.organization_id not in {None, organization_id}
            ):
                raise ValidationError({"requirements": "Capability concept is not approved or visible."})
            if supplied_knowledge_evidence is not None and capability_knowledge_evidence is None:
                raise ValidationError({"requirements": "Capability knowledge evidence is invalid."})
            if capability_knowledge_evidence is not None and (
                capability is None
                or capability_knowledge_evidence.status != KnowledgeStatus.APPROVED
                or capability_knowledge_evidence.organization_id not in {None, organization_id}
                or not capability.evidence.filter(pk=capability_knowledge_evidence.pk).exists()
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


__all__ = [
    "LeadService",
    "LeadStateError",
    "LeadVersionConflict",
    "canonical_lead_insight_output",
]
