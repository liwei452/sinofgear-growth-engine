from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import ProtectedError

from apps.leads.models import (
    LeadCandidate,
    LeadCandidateEvidence,
    LeadInsight,
    LeadInsightRequirement,
)
from apps.leads.services import LeadService, LeadStateError, LeadVersionConflict


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
def test_candidate_normalizes_public_company_domain(candidate):
    assert candidate.company_domain == "example.com"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "domain",
    [
        "https://user:secret@example.com",
        "https://example.com/path",
        "https://example.com?from=lead",
        "https://example.com/#profile",
        "127.0.0.1",
        "127.1",
        "0177.0.0.1",
        "0x7f.0.0.1",
        "2130706433",
        "8.8.8.8",
        "localhost",
        "machine.internal",
        "example.local",
        "device.home.arpa",
        "hidden-service.onion",
        "reserved.example.test",
        "reserved.example.invalid",
        "not_a_domain",
    ],
)
def test_candidate_rejects_non_public_or_non_domain_company_values(
    organization, signal, user, domain
):
    with pytest.raises(ValidationError):
        LeadCandidate.objects.create(
            organization=organization,
            source_signal=signal,
            company_domain=domain,
            created_by=user,
        )


@pytest.mark.django_db
def test_candidate_exposes_exact_state_vocabulary():
    assert set(LeadCandidate.Status.values) == {
        "DISCOVERED",
        "ANALYZING",
        "ANALYZED",
        "REVIEWED",
        "READY_FOR_HANDOFF",
        "HANDED_OFF",
        "DISMISSED",
    }


@pytest.mark.django_db
def test_candidate_must_be_created_as_discovered(organization, signal, user):
    with pytest.raises(ValidationError):
        LeadCandidate.objects.create(
            organization=organization,
            source_signal=signal,
            status=LeadCandidate.Status.READY_FOR_HANDOFF,
            created_by=user,
        )


@pytest.mark.django_db
def test_b1_state_service_accepts_only_defined_transitions(candidate):
    assert transition(candidate=candidate, to_status="ANALYZING").status == "ANALYZING"
    assert transition(candidate=candidate, to_status="ANALYZED").status == "ANALYZED"
    assert transition(candidate=candidate, to_status="REVIEWED").status == "REVIEWED"
    assert transition(candidate=candidate, to_status="DISMISSED").status == "DISMISSED"
    assert transition(candidate=candidate, to_status="DISCOVERED").status == "DISCOVERED"


@pytest.mark.django_db
@pytest.mark.parametrize("forbidden_status", ["READY_FOR_HANDOFF", "HANDED_OFF", "REVIEWED"])
def test_b1_state_service_rejects_handoff_and_skipped_transitions(candidate, forbidden_status):
    with pytest.raises(LeadStateError):
        transition(candidate=candidate, to_status=forbidden_status)


@pytest.mark.django_db
def test_new_analysis_appends_insight_and_preserves_previous(
    candidate, evidence, ai_run, ai_run_factory, insight_payload, analysis_snapshot
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    first_payload = insight_payload(intent=19, company_fit=18, specificity=15, capability_fit=10, recency=10)
    second_payload = insight_payload(intent=30, company_fit=22, specificity=18, capability_fit=10, recency=5)

    first = record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=first_payload
    )
    second = record_insight(
        candidate=candidate,
        ai_run=ai_run_factory(
            candidate.organization,
            input_snapshot=analysis_snapshot(
                candidate=candidate,
                evidence=[evidence],
                ontology_snapshot=second_payload["ontology_snapshot"],
            ),
        ),
        evidence=[evidence],
        payload=second_payload,
    )

    assert [first.version, second.version] == [1, 2]
    assert LeadInsight.objects.filter(candidate=candidate).count() == 2
    assert LeadInsight.objects.get(pk=first.pk).score == 72
    candidate.refresh_from_db()
    assert candidate.latest_insight_id == second.id
    assert candidate.status == LeadCandidate.Status.ANALYZED
    assert candidate.version == 4


@pytest.mark.django_db
def test_one_audited_run_cannot_create_multiple_insights(
    candidate, evidence, ai_run, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate,
            ai_run=ai_run,
            evidence=[evidence],
            payload=insight_payload(),
        )

    assert candidate.insights.count() == 1


@pytest.mark.django_db
def test_reviewed_candidate_rejects_unreviewed_insight_append(
    candidate, evidence, ai_run, ai_run_factory, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )
    transition(candidate=candidate, to_status=LeadCandidate.Status.REVIEWED)

    with pytest.raises(LeadStateError):
        record_insight(
            candidate=candidate,
            ai_run=ai_run_factory(candidate.organization),
            evidence=[evidence],
            payload=insight_payload(),
        )

    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.REVIEWED
    assert candidate.insights.count() == 1


@pytest.mark.django_db
def test_insight_preserves_scores_explanation_confidence_and_ontology(
    candidate, evidence, ai_run, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate,
        ai_run=ai_run,
        evidence=[evidence],
        payload=insight_payload(intent=30, company_fit=25, specificity=20, capability_fit=15, recency=10),
    )

    assert (
        insight.intent_score,
        insight.company_fit_score,
        insight.specificity_score,
        insight.capability_fit_score,
        insight.recency_score,
    ) == (30, 25, 20, 15, 10)
    assert insight.score == 100
    assert insight.score_band == LeadInsight.ScoreBand.HIGH
    assert insight.high_value_eligible is True
    assert insight.explanation["reasons"][0]["evidence_ids"] == [str(evidence.id)]
    assert insight.extracted_requirement_values[0]["value"] == "200"
    assert insight.evidence_confidence == Decimal("0.9500")
    assert insight.company_match_confidence == Decimal("0.8000")
    assert insight.ai_confidence == Decimal("0.9000")
    assert insight.ontology_snapshot["organization_id"] == str(candidate.organization_id)


@pytest.mark.django_db
def test_recording_insight_creates_traceable_append_only_evidence_and_requirement(
    candidate,
    evidence,
    ai_run,
    insight_payload,
    approved_requirement,
    approved_capability,
    approved_capability_evidence,
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )

    link = LeadCandidateEvidence.objects.get(candidate=candidate, insight=insight)
    requirement = LeadInsightRequirement.objects.get(insight=insight)
    assert link.evidence_id == evidence.id
    assert link.source_signal_id == evidence.source_signal_id
    assert requirement.requirement_concept_id == approved_requirement.id
    assert requirement.capability_concept_id == approved_capability.id
    assert requirement.capability_knowledge_evidence_id == approved_capability_evidence.id
    assert requirement.source_evidence_id == evidence.id
    assert requirement.extracted_value == "200"
    assert requirement.unit == "pcs"

    link.evidence = evidence
    with pytest.raises(ValidationError):
        link.save()
    with pytest.raises(ProtectedError):
        LeadCandidateEvidence.objects.filter(pk=link.pk).delete()
    requirement.extracted_value = "201"
    with pytest.raises(ValidationError):
        requirement.save()


@pytest.mark.django_db
def test_capability_gate_requires_approved_knowledge_evidence(
    candidate, evidence, ai_run, insight_payload
):
    payload = insight_payload()
    payload["requirements"][0].pop("capability_knowledge_evidence")
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)

    with pytest.raises(ValidationError):
        record_insight(
            candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload
        )


@pytest.mark.django_db
def test_insight_history_cannot_be_updated_or_deleted(
    candidate, evidence, ai_run, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )

    insight.explanation = {"forged": True}
    with pytest.raises(ValidationError):
        insight.save()
    with pytest.raises(ValidationError):
        LeadInsight.objects.filter(pk=insight.pk).update(score=1)
    with pytest.raises(ProtectedError):
        insight.delete()


@pytest.mark.django_db
def test_candidate_local_insight_version_is_unique(
    candidate, evidence, ai_run, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )

    with pytest.raises(ValidationError):
        LeadInsight.objects.create(
            organization=candidate.organization,
            candidate=candidate,
            ai_run=ai_run,
            version=insight.version,
            intent_score=1,
            company_fit_score=1,
            specificity_score=1,
            capability_fit_score=1,
            recency_score=1,
            score=5,
            score_band=LeadInsight.ScoreBand.LOW,
            ontology_snapshot={"organization_id": str(candidate.organization_id)},
        )


@pytest.mark.django_db
def test_latest_insight_cannot_be_rewound(
    candidate, evidence, ai_run, ai_run_factory, insight_payload, analysis_snapshot
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    first = record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )
    second_payload = insight_payload()
    record_insight(
        candidate=candidate,
        ai_run=ai_run_factory(
            candidate.organization,
            input_snapshot=analysis_snapshot(
                candidate=candidate,
                evidence=[evidence],
                ontology_snapshot=second_payload["ontology_snapshot"],
            ),
        ),
        evidence=[evidence],
        payload=second_payload,
    )
    candidate.refresh_from_db()
    candidate.latest_insight = first

    with pytest.raises(ValidationError):
        candidate.save()


@pytest.mark.django_db
def test_latest_insight_cannot_be_cleared_after_history_exists(
    candidate, evidence, ai_run, insight_payload
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    record_insight(
        candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=insight_payload()
    )
    candidate.latest_insight = None

    with pytest.raises(ValidationError):
        candidate.save()


@pytest.mark.django_db
def test_candidate_direct_save_detects_interleaved_version_change(candidate, monkeypatch):
    original_full_clean = LeadCandidate.full_clean
    injected = False

    def full_clean_then_interleave(instance, *args, **kwargs):
        nonlocal injected
        original_full_clean(instance, *args, **kwargs)
        if not injected and instance.pk == candidate.pk:
            injected = True
            models.QuerySet.update(
                LeadCandidate._base_manager.filter(pk=instance.pk),
                company_name="Concurrent writer",
                version=instance.version + 1,
            )

    monkeypatch.setattr(LeadCandidate, "full_clean", full_clean_then_interleave)
    candidate.company_name = "Stale writer"

    with pytest.raises(LeadVersionConflict):
        candidate.save(update_fields=["company_name", "updated_at"])

    candidate.refresh_from_db()
    assert candidate.company_name == "ABC Packaging"
    assert candidate.version == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "invalid_values",
    [
        {"intent_score": 31},
        {"evidence_confidence": Decimal("1.1000")},
        {"score": 99},
        {"score_band": LeadInsight.ScoreBand.LOW},
        {"traceable_source": False, "high_value_eligible": True},
    ],
)
def test_database_rejects_inconsistent_immutable_score_rows(
    candidate, evidence, ai_run, insight_payload, invalid_values
):
    transition(candidate=candidate, to_status=LeadCandidate.Status.ANALYZING)
    insight = record_insight(
        candidate=candidate,
        ai_run=ai_run,
        evidence=[evidence],
        payload=insight_payload(
            intent=30,
            company_fit=25,
            specificity=20,
            capability_fit=15,
            recency=10,
        ),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        models.QuerySet.update(
            LeadInsight._base_manager.filter(pk=insight.pk),
            **invalid_values,
        )
