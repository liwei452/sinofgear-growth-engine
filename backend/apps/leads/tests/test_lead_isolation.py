import pytest
from django.core.exceptions import ValidationError

from apps.jobs.models import Job
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import KnowledgeConcept, KnowledgeStatus
from apps.leads.models import LeadCandidate
from apps.leads.services import LeadService


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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
            candidate=candidate,
            ai_run=unrelated_run,
            evidence=[evidence],
            payload=insight_payload(),
        )

    assert candidate.insights.count() == 0


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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_ontology_snapshot_must_belong_to_candidate_organization(
    candidate, evidence, ai_run, insight_payload, other_organization
):
    payload = insight_payload()
    payload["ontology_snapshot"]["organization_id"] = str(other_organization.id)
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
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
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0


@pytest.mark.django_db
def test_complete_snapshot_must_include_linked_ontology_objects(
    candidate, evidence, ai_run, insight_payload
):
    payload = insight_payload()
    payload["ontology_snapshot"]["concept_ids"] = []
    payload["ontology_snapshot"]["evidence_ids"] = []
    LeadService.transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        LeadService.record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )

    assert candidate.insights.count() == 0
