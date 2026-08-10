from copy import deepcopy

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from apps.identity.models import Membership, Role
from apps.leads.models import LeadCandidate, LeadInsight, LeadReview, LeadVersionConflict
from apps.leads.services import LeadReviewService, LeadService, LeadStateError
from apps.sources.models import SourceEvidence


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(user, organization):
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_reviewer(),
    )
    return user


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
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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


def test_confirm_protects_every_linked_evidence(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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


def test_identical_review_retry_is_idempotent(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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
    candidate, evidence, ai_run, insight_payload, reviewer
):
    user = reviewer
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
def test_b2_review_actions_are_reserved(candidate, reviewer, action):
    user = reviewer
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


@pytest.mark.parametrize("membership_kind", ["missing", "foreign", "inactive", "unauthorized"])
def test_direct_review_service_requires_active_same_org_review_permission(
    candidate,
    evidence,
    ai_run,
    insight_payload,
    user,
    other_organization,
    membership_kind,
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    if membership_kind == "foreign":
        Membership.objects.create(
            user=user,
            organization=other_organization,
            role=Role.objects.create_reviewer(),
        )
    elif membership_kind == "inactive":
        Membership.objects.create(
            user=user,
            organization=candidate.organization,
            role=Role.objects.create_reviewer(),
            status=Membership.Status.INACTIVE,
        )
    elif membership_kind == "unauthorized":
        Membership.objects.create(
            user=user,
            organization=candidate.organization,
            role=Role.objects.create_operator(),
        )

    with pytest.raises(PermissionDenied):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.CONFIRM,
            expected_version=candidate.version,
            reason="Unauthorized direct service call.",
            reviewer=user,
            idempotency_key=f"unauthorized-{membership_kind}",
        )
    assert not LeadReview.objects.filter(candidate=candidate).exists()


def test_dismiss_then_reopen_preserves_append_only_history(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    dismissed = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.DISMISS,
        expected_version=candidate.version,
        reason="Not relevant now.",
        reviewer=reviewer,
        idempotency_key="dismiss-positive",
    )
    reopened = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.REOPEN,
        expected_version=dismissed.candidate.version,
        reason="New public evidence warrants another analysis.",
        reviewer=reviewer,
        idempotency_key="reopen-positive",
    )
    assert reopened.candidate.status == LeadCandidate.Status.DISCOVERED
    assert list(
        LeadReview.objects.filter(candidate=candidate).values_list("action", flat=True)
    ) == [LeadReview.Action.DISMISS, LeadReview.Action.REOPEN]


def test_request_more_evidence_appends_history_without_inventing_state(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    result = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.REQUEST_MORE_EVIDENCE,
        expected_version=candidate.version,
        reason="Need a public company capability page.",
        reviewer=reviewer,
        idempotency_key="request-more-evidence",
    )
    assert result.candidate.status == LeadCandidate.Status.ANALYZED
    assert result.review.action == LeadReview.Action.REQUEST_MORE_EVIDENCE
    assert result.insight.id == candidate.latest_insight_id


def test_correction_cannot_remove_last_enterprise_identity(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    with pytest.raises(ValidationError, match="company name or public company domain"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.CORRECT,
            expected_version=candidate.version,
            correction={"company_name": "", "company_domain": ""},
            reason="Invalid empty enterprise identity.",
            reviewer=reviewer,
            idempotency_key="empty-enterprise-correction",
        )
    assert LeadReview.objects.filter(candidate=candidate).count() == 0


def test_dismiss_refuses_legacy_empty_identity_without_shared_fingerprint(
    candidate, evidence, ai_run, insight_payload, reviewer
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    models.QuerySet.update(
        LeadCandidate._base_manager.filter(pk=candidate.pk),
        company_name="",
        company_domain="",
    )
    candidate.refresh_from_db()
    with pytest.raises(LeadStateError, match="enterprise identity"):
        LeadReviewService.apply(
            organization=candidate.organization,
            candidate=candidate,
            action=LeadReview.Action.DISMISS,
            expected_version=candidate.version,
            reason="Cannot fingerprint an empty identity.",
            reviewer=reviewer,
            idempotency_key="empty-dismiss",
        )
    assert not LeadReview.objects.filter(candidate=candidate).exists()


def test_same_organization_distinct_enterprises_have_distinct_ignore_fingerprints(
    candidate,
    evidence,
    second_source_pair,
    ai_run,
    insight_payload,
    reviewer,
):
    _analyzed(candidate, evidence, ai_run, insight_payload)
    candidate.refresh_from_db()
    other = LeadCandidate.objects.create(
        organization=candidate.organization,
        source_signal=second_source_pair[0],
        company_name="Different Enterprise",
        created_by=reviewer,
    )
    models.QuerySet.update(
        LeadCandidate._base_manager.filter(pk=other.pk),
        status=LeadCandidate.Status.ANALYZED,
    )
    other.refresh_from_db()

    first = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=candidate,
        action=LeadReview.Action.DISMISS,
        expected_version=candidate.version,
        reason="First enterprise is not relevant.",
        reviewer=reviewer,
        idempotency_key="dismiss-first-enterprise",
    )
    second = LeadReviewService.apply(
        organization=candidate.organization,
        candidate=other,
        action=LeadReview.Action.DISMISS,
        expected_version=other.version,
        reason="Second enterprise is not relevant.",
        reviewer=reviewer,
        idempotency_key="dismiss-second-enterprise",
    )
    assert first.review.ignore_fingerprint
    assert second.review.ignore_fingerprint
    assert first.review.ignore_fingerprint != second.review.ignore_fingerprint
