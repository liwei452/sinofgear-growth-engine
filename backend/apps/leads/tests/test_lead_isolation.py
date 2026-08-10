from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from apps.jobs.models import Job
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeStatus,
)
from apps.knowledge.services import build_frozen_snapshot
from apps.leads.models import LeadCandidate
from apps.leads.services import LeadService


def transition(*, candidate, organization=None, **kwargs):
    return LeadService.transition(
        organization=organization or candidate.organization,
        candidate=candidate,
        **kwargs,
    )


def record_insight(*, candidate, organization=None, **kwargs):
    return LeadService.record_insight(
        organization=organization or candidate.organization,
        candidate=candidate,
        **kwargs,
    )


@pytest.mark.django_db
def test_candidate_rejects_source_signal_from_another_organization(
    organization, other_source_pair, user
):
    other_signal, _other_evidence = other_source_pair

    with pytest.raises(ValidationError):
        LeadCandidate.objects.create(
            organization=organization,
            source_signal=other_signal,
            company_name="Wrong organization",
            created_by=user,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("as_uuid", [False, True])
def test_service_resolves_candidate_only_inside_explicit_active_organization(
    organization, other_organization, other_source_pair, user, as_uuid
):
    other_signal, _other_evidence = other_source_pair
    foreign_candidate = LeadCandidate.objects.create(
        organization=other_organization,
        source_signal=other_signal,
        company_name="Foreign candidate",
        created_by=user,
    )
    reference = foreign_candidate.id if as_uuid else foreign_candidate

    with pytest.raises(LeadCandidate.DoesNotExist):
        transition(
            organization=organization,
            candidate=reference,
            to_status=LeadCandidate.Status.ANALYZING,
        )


@pytest.mark.django_db
def test_candidate_checks_persisted_signal_organization_not_mutable_instance(
    organization, other_source_pair, user
):
    other_signal, _other_evidence = other_source_pair
    other_signal.organization = organization

    with pytest.raises(ValidationError):
        LeadCandidate.objects.create(
            organization=organization,
            source_signal=other_signal,
            company_name="Forged relation",
            created_by=user,
        )


@pytest.mark.django_db
def test_candidate_organization_is_immutable(candidate, other_organization):
    candidate.organization = other_organization

    with pytest.raises(ValidationError):
        candidate.save()
    with pytest.raises(ValidationError):
        LeadCandidate.objects.filter(pk=candidate.pk).update(organization=other_organization)


@pytest.mark.django_db
def test_record_insight_rejects_other_organization_evidence(
    candidate, other_source_pair, ai_run, insight_payload
):
    _other_signal, other_evidence = other_source_pair
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=ai_run,
            evidence=[other_evidence],
            payload=insight_payload(),
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_record_insight_rejects_other_organization_ai_run(
    candidate, evidence, ai_run_factory, other_organization, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=ai_run_factory(other_organization),
            evidence=[evidence],
            payload=insight_payload(),
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_record_insight_rejects_successful_run_for_another_purpose(
    candidate, evidence, ai_run_factory, insight_payload
):
    unrelated_run = ai_run_factory(
        candidate.organization,
        job_type=Job.Type.CONTENT_GENERATE,
        purpose="CONTENT_GENERATE",
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=unrelated_run,
            evidence=[evidence],
            payload=insight_payload(),
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_audited_run_is_bound_to_exact_candidate(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
    signal,
    user,
):
    payload = insight_payload()
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=payload["ontology_snapshot"],
        ),
        output_payload=payload,
    )
    other_candidate = LeadCandidate.objects.create(
        organization=candidate.organization,
        source_signal=signal,
        company_name="Different company",
        created_by=user,
    )
    transition(candidate=other_candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=other_candidate,
            ai_run=run,
            evidence=[evidence],
            payload=payload,
        )

    assert other_candidate.insights.count() == 0


@pytest.mark.django_db
def test_audited_run_is_bound_to_exact_evidence_set(
    candidate,
    evidence,
    second_source_pair,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
):
    _second_signal, second_evidence = second_source_pair
    payload = insight_payload()
    payload["explanation"]["reasons"][0]["evidence_ids"] = [str(second_evidence.id)]
    payload["requirements"][0]["evidence"] = second_evidence
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=payload["ontology_snapshot"],
        ),
        output_payload=payload,
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=run,
            evidence=[second_evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_persisted_ontology_must_equal_frozen_ai_run_snapshot(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
):
    payload = insight_payload()
    frozen_input = analysis_snapshot(
        candidate=candidate,
        evidence=[evidence],
        ontology_snapshot=payload["ontology_snapshot"],
    )
    payload["ontology_snapshot"]["generated_at"] = "forged-after-run"
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=frozen_input,
        output_payload=payload,
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=run,
            evidence=[evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_tampered_frozen_ontology_digest_is_rejected(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
):
    payload = insight_payload()
    payload["ontology_snapshot"]["concept_versions"][0]["code"] = "FORGED_CODE"
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=payload["ontology_snapshot"],
        ),
        output_payload=payload,
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=run,
            evidence=[evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_tampered_frozen_ontology_evidence_is_rejected(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
):
    payload = insight_payload()
    payload["ontology_snapshot"]["evidence_references"][0]["captured_at"] = (
        "2026-08-09 00:00:00+00:00"
    )
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=payload["ontology_snapshot"],
        ),
        output_payload=payload,
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=run,
            evidence=[evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("original_text", "Different public statement"),
        ("source_url", "https://attacker.example/forged"),
        ("collection_method", "API"),
        ("source_content_id", None),
    ],
)
def test_audited_run_rejects_tampered_full_evidence_snapshot(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
    field_name,
    forged_value,
):
    payload = insight_payload()
    frozen_input = analysis_snapshot(
        candidate=candidate,
        evidence=[evidence],
        ontology_snapshot=payload["ontology_snapshot"],
    )
    frozen_input["evidence"][0][field_name] = forged_value
    run = ai_run_factory(
        candidate.organization,
        input_snapshot=frozen_input,
        output_payload=payload,
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=run,
            evidence=[evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_saved_conclusions_must_equal_successful_ai_run_output(
    candidate, evidence, ai_run, insight_payload
):
    payload = insight_payload()
    payload["explanation"]["reasons"][0]["text"] = "Tampered after successful run"
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=ai_run,
            evidence=[evidence],
            payload=payload,
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_historical_frozen_ontology_remains_valid_after_current_graph_changes(
    candidate,
    evidence,
    ai_run_factory,
    insight_payload,
    analysis_snapshot,
    approved_requirement,
    approved_capability,
    organization,
    user,
):
    with _test_fixture_writes():
        relation = KnowledgeRelation.objects.create(
            organization=organization,
            subject_concept=approved_capability,
            predicate=KnowledgeRelation.Predicate.SATISFIES,
            object_concept=approved_requirement,
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
        historical_evidence = KnowledgeEvidence.objects.create(
            organization=organization,
            evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
            excerpt="Historical relation evidence",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
    relation.evidence.add(historical_evidence)
    frozen_ontology = build_frozen_snapshot(
        organization=organization,
        concept_ids=[approved_capability.id],
    )
    payload = insight_payload()
    payload["ontology_snapshot"] = deepcopy(frozen_ontology)
    run = ai_run_factory(
        organization,
        input_snapshot=analysis_snapshot(
            candidate=candidate,
            evidence=[evidence],
            ontology_snapshot=frozen_ontology,
        ),
        output_payload=payload,
    )

    approved_capability.label_en = "Changed after the run started"
    approved_capability.version += 1
    relation.status = KnowledgeStatus.DEPRECATED
    relation.version += 1
    historical_evidence.status = KnowledgeStatus.DEPRECATED
    historical_evidence.version += 1
    with _test_fixture_writes():
        approved_capability.save()
        relation.save()
        historical_evidence.save()

    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate,
        ai_run=run,
        evidence=[evidence],
        payload=payload,
    )

    assert insight.ontology_snapshot == frozen_ontology


@pytest.mark.django_db
def test_requirement_link_rejects_unapproved_and_foreign_ontology(
    candidate, evidence, ai_run, insight_payload, other_organization, user
):
    with _test_fixture_writes():
        foreign_requirement = KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.ORGANIZATION,
            organization=other_organization,
            concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
            code="REQ_FOREIGN",
            label_zh="其他组织要求",
            label_en="Foreign requirement",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
    payload = insight_payload()
    payload["requirements"][0]["requirement_concept"] = foreign_requirement
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_requirement_link_checks_persisted_concept_state(
    candidate, evidence, ai_run, insight_payload, organization, user
):
    suggested = KnowledgeConcept.objects.create(
        scope=KnowledgeConcept.Scope.ORGANIZATION,
        organization=organization,
        concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
        code="REQ_SUGGESTED",
        label_zh="待审核要求",
        label_en="Suggested requirement",
        status=KnowledgeStatus.SUGGESTED,
        created_by=user,
    )
    suggested.status = KnowledgeStatus.APPROVED
    payload = insight_payload()
    payload["requirements"][0]["requirement_concept"] = suggested
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_ontology_snapshot_must_belong_to_candidate_organization(
    candidate, evidence, ai_run, insight_payload, other_organization
):
    payload = insight_payload()
    payload["ontology_snapshot"]["organization_id"] = str(other_organization.id)
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_incomplete_snapshot_still_cannot_claim_another_organization(
    candidate, evidence, ai_run, insight_payload, other_organization
):
    payload = insight_payload()
    payload["gates"]["ontology_snapshot"] = False
    payload["ontology_snapshot"]["organization_id"] = str(other_organization.id)
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_complete_snapshot_must_include_linked_ontology_objects(
    candidate, evidence, ai_run, insight_payload
):
    payload = insight_payload()
    payload["ontology_snapshot"]["concept_versions"] = []
    payload["ontology_snapshot"]["evidence_references"] = []
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0
