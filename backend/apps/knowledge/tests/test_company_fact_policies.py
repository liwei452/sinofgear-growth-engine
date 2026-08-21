from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    CompanyFact,
    CompanyFactEvidence,
    CompanyKnowledgeProfile,
    KnowledgeEvidence,
    KnowledgeStatus,
)
from apps.knowledge.policies import evaluate_company_fact_public_eligibility


def make_public_fact(organization):
    actor = get_user_model().objects.create_user(username="policy-reviewer")
    with _test_fixture_writes():
        profile = CompanyKnowledgeProfile.objects.create(
            organization=organization,
            brand_name="SINOF",
            status=CompanyKnowledgeProfile.Status.APPROVED,
            created_by=actor,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
    with _test_fixture_writes():
        fact = CompanyFact.objects.create(
            organization=organization,
            profile=profile,
            namespace="company",
            key="brand_name",
            value_json={"value": "SINOF"},
            fact_type="TEXT",
            status=CompanyFact.Status.VERIFIED,
            visibility=CompanyFact.Visibility.PUBLIC,
            sensitivity=CompanyFact.Sensitivity.NORMAL,
            claim_policy=CompanyFact.ClaimPolicy.ALLOW_WITH_EVIDENCE,
            is_demo=False,
            created_by=actor,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
    return fact, actor


def bind_evidence(fact, actor, *, support_type=CompanyFactEvidence.SupportType.PRIMARY, **overrides):
    values = {
        "organization": fact.organization,
        "evidence_type": KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        "excerpt": "Approved source",
        "status": KnowledgeStatus.APPROVED,
        "usage_rights": KnowledgeEvidence.UsageRights.PUBLIC,
        "sensitivity": KnowledgeEvidence.Sensitivity.NORMAL,
        "is_demo": False,
    }
    values.update(overrides)
    with _test_fixture_writes():
        evidence = KnowledgeEvidence.objects.create(**values)
    with _test_fixture_writes():
        return CompanyFactEvidence.objects.create(
            company_fact=fact,
            evidence=evidence,
            support_type=support_type,
            citation_label="Evidence",
            bound_by=actor,
        )


@pytest.mark.django_db
def test_public_eligibility_accepts_only_fully_qualified_fact(organizations) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor)

    decision = evaluate_company_fact_public_eligibility(fact)

    assert decision.eligible is True
    assert decision.blocking_reasons == ()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "profile_status",
    [
        CompanyKnowledgeProfile.Status.DRAFT,
        CompanyKnowledgeProfile.Status.IN_REVIEW,
        CompanyKnowledgeProfile.Status.SUPERSEDED,
    ],
)
def test_public_eligibility_rejects_fact_under_nonapproved_profile(
    organizations, profile_status
) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor)
    with _test_fixture_writes():
        CompanyKnowledgeProfile.objects.filter(pk=fact.profile_id).update(status=profile_status)

    decision = evaluate_company_fact_public_eligibility(fact)

    assert decision.eligible is False
    assert "PROFILE_NOT_APPROVED" in {item.code for item in decision.blocking_reasons}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("status", CompanyFact.Status.DRAFT, "FACT_NOT_VERIFIED"),
        ("visibility", CompanyFact.Visibility.INTERNAL, "FACT_NOT_PUBLIC"),
        ("sensitivity", CompanyFact.Sensitivity.CONFIDENTIAL, "FACT_SENSITIVE"),
        ("claim_policy", CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY, "CLAIM_POLICY_BLOCKED"),
        ("is_demo", True, "FACT_IS_DEMO"),
        ("valid_until", timezone.localdate() - timedelta(days=1), "FACT_EXPIRED"),
    ],
)
def test_public_eligibility_returns_structured_fact_blocking_reasons(
    organizations, field, value, reason
) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor)
    with _test_fixture_writes():
        CompanyFact.objects.filter(pk=fact.pk).update(**{field: value})
    fact.refresh_from_db()

    decision = evaluate_company_fact_public_eligibility(fact)

    assert decision.eligible is False
    assert reason in {item.code for item in decision.blocking_reasons}
    assert all(item.message for item in decision.blocking_reasons)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("evidence_overrides", "reason"),
    [
        ({"status": KnowledgeStatus.SUGGESTED}, "MISSING_PUBLIC_EVIDENCE"),
        ({"usage_rights": KnowledgeEvidence.UsageRights.UNKNOWN}, "MISSING_PUBLIC_EVIDENCE"),
        ({"sensitivity": KnowledgeEvidence.Sensitivity.CONFIDENTIAL}, "MISSING_PUBLIC_EVIDENCE"),
        ({"is_demo": True}, "MISSING_PUBLIC_EVIDENCE"),
        ({"expires_at": timezone.now() - timedelta(seconds=1)}, "MISSING_PUBLIC_EVIDENCE"),
    ],
)
def test_public_eligibility_rejects_ineligible_evidence(organizations, evidence_overrides, reason) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor, **evidence_overrides)

    decision = evaluate_company_fact_public_eligibility(fact)

    assert decision.eligible is False
    assert reason in {item.code for item in decision.blocking_reasons}


@pytest.mark.django_db
def test_contradicting_evidence_blocks_otherwise_public_fact(organizations) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor)
    bind_evidence(
        fact,
        actor,
        support_type=CompanyFactEvidence.SupportType.CONTRADICTING,
        excerpt="Still-valid contradiction",
    )

    decision = evaluate_company_fact_public_eligibility(fact)

    assert decision.eligible is False
    assert "CONTRADICTING_EVIDENCE" in {item.code for item in decision.blocking_reasons}


@pytest.mark.django_db
def test_expired_contradiction_does_not_block_public_fact(organizations) -> None:
    fact, actor = make_public_fact(organizations[0])
    bind_evidence(fact, actor)
    bind_evidence(
        fact,
        actor,
        support_type=CompanyFactEvidence.SupportType.CONTRADICTING,
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    assert evaluate_company_fact_public_eligibility(fact).eligible is True
