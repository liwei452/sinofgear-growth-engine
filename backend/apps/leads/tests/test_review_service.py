from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from apps.leads.models import LeadCandidate, LeadInsight, LeadReview, LeadVersionConflict
from apps.leads.services import LeadReviewService, LeadService, LeadStateError
from apps.sources.models import SourceEvidence


pytestmark = pytest.mark.django_db


def _analyzed(candidate, evidence, ai_run, insight_payload):
    LeadService.begin_analysis(
        organization=candidate.organization,
        candidate=candidate,
        expected_version=candidate.version,
    )
    return LeadService.record_insight(
        organization=candidate.organization,
        candidate=candidate,
        ai_run=ai_run,
        evidence=[evidence],
        payload=insight_payload(),
    )


def test_correction_appends_insight_and_review_without_mutating_ai_history(
    candidate, evidence, ai_run, insight_payload, user
):
    original = _analyzed(candidate, evidence, ai_run, insight_payload)
    original_values = deepcopy(original.explanation)
    candidate.refresh_from_db()

    result = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.CORRECT,
        expected_version=candidate.version,
        correction={
            "company_name": "ABC Packaging GmbH",
            "dimension_overrides": {"company_fit": 22},
        },
        reason="Public company page confirms the enterprise name.",
        reviewer=user,
        idempotency_key="review-correct-1",
    )

    original.refresh_from_db()
    candidate.refresh_from_db()
    assert original.explanation == original_values
    assert result.insight.version == 2
    assert result.insight.source_insight_id == original.id
    assert result.insight.origin == LeadInsight.Origin.HUMAN_CORRECTION
    assert result.insight.company_fit_score == 22
    assert result.insight.score == original.score + 2
    assert result.insight.human_correction["company_name"] == "ABC Packaging GmbH"
    assert result.insight.reviewed_by_id == user.id
    assert result.review.insight_id == result.insight.id
    assert candidate.latest_insight_id == result.insight.id
    assert candidate.company_name == "ABC Packaging GmbH"
    assert candidate.status == LeadCandidate.Status.REVIEWED


def test_confirm_protects_every_linked_evidence(candidate, evidence, ai_run, insight_payload, user):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()

    LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.CONFIRM,
        expected_version=candidate.version,
        reason="Evidence is sufficient for human confirmation.",
        reviewer=user,
        idempotency_key="review-confirm-1",
    )

    candidate.refresh_from_db()
    evidence.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.REVIEWED
    assert evidence.retention_class == SourceEvidence.RetentionClass.CONFIRMED


def test_identical_review_retry_is_idempotent(candidate, evidence, ai_run, insight_payload, user):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    kwargs = {
        "organization": candidate.organization,
        "candidate": candidate,
        "action": LeadReview.Action.CONFIRM,
        "expected_version": candidate.version,
        "reason": "Confirmed once.",
        "reviewer": user,
        "idempotency_key": "review-confirm-retry",
    }

    first = LeadReviewService.apply(**kwargs)
    second = LeadReviewService.apply(**kwargs)

    assert second.review.id == first.review.id
    assert LeadReview.objects.filter(candidate=candidate).count() == 1


def test_review_idempotency_key_rejects_different_intent(
    candidate, evidence, ai_run, insight_payload, user
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.CONFIRM,
        expected_version=candidate.version,
        reason="Confirmed once.",
        reviewer=user,
        idempotency_key="review-conflict",
    )

    with pytest.raises(LeadStateError, match="Idempotency"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.DISMISS,
            expected_version=candidate.version,
            reason="Different intent.",
            reviewer=user,
            idempotency_key="review-conflict",
        )


def test_correction_cannot_forge_system_evidence_gates(
    candidate, evidence, ai_run, insight_payload, user
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()

    with pytest.raises(ValidationError, match="Gate overrides"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.CORRECT,
            expected_version=candidate.version,
            correction={"gate_overrides": {"capability_evidence": True}},
            reason="This gate is determined by evidence, not a reviewer assertion.",
            reviewer=user,
            idempotency_key="review-forged-gate",
        )


def test_stale_and_active_lease_reviews_are_rejected(
    candidate, evidence, ai_run, insight_payload, user
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    with pytest.raises(LeadVersionConflict):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.CONFIRM,
            expected_version=candidate.version - 1,
            reason="Stale review.",
            reviewer=user,
            idempotency_key="review-stale",
        )

    LeadService.begin_analysis(
        organization=candidate.organization,
        candidate=candidate,
        expected_version=candidate.version,
    )
    candidate.refresh_from_db()
    with pytest.raises(LeadStateError, match="active analysis lease"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.REQUEST_MORE_EVIDENCE,
            expected_version=candidate.version,
            reason="Need a public company page.",
            reviewer=user,
            idempotency_key="review-active-lease",
        )


@pytest.mark.parametrize("action", ["MERGE_COMPANY", "SPLIT_COMPANY"])
def test_b2_review_actions_are_reserved(candidate, user, action):
    with pytest.raises(ValidationError, match="reserved"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=action,
            expected_version=candidate.version,
            reason="B2 only.",
            reviewer=user,
            idempotency_key=f"reserved-{action}",
        )
