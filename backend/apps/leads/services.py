import hashlib
import hmac
import json
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.ai.models import AIRun
from apps.jobs.models import Job
from apps.sources.models import SourceEvidence

from .models import (
    LeadCandidate,
    LeadCandidateEvidence,
    LeadInsight,
    LeadInsightRequirement,
    LeadVersionConflict,
    lead_analysis_lease_writes,
    lead_frozen_reference_writes,
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
        if locked.status == LeadCandidate.Status.DISCOVERED:
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
        if audited_output is not None:
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
        if (
            started_from == LeadCandidate.Status.DISCOVERED
            and candidate.status == LeadCandidate.Status.ANALYZING
        ):
            candidate.status = LeadCandidate.Status.DISCOVERED
        elif started_from != LeadCandidate.Status.ANALYZED:
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
            return
        if candidate.analysis_lease_token is not None:
            raise LeadStateError("Lead candidate is owned by another analysis.")
        expected_status = (
            LeadCandidate.Status.DISCOVERED
            if started_from == LeadCandidate.Status.DISCOVERED
            else LeadCandidate.Status.ANALYZED
        )
        if candidate.status != expected_status:
            raise LeadStateError("Lead candidate is not recoverable for retry.")
        if started_from == LeadCandidate.Status.DISCOVERED:
            candidate.status = LeadCandidate.Status.ANALYZING
        candidate.analysis_lease_token = analysis_lease_token
        with lead_analysis_lease_writes():
            candidate.save(
                update_fields=["status", "analysis_lease_token", "updated_at"]
            )

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
        if not isinstance(frozen, dict) or run.job.input_snapshot != frozen:
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


__all__ = [
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
    organization = membership.organization
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
