import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.knowledge.models import (
    CompanyFact,
    CompanyFactEvidence,
    CompanyKnowledgeProfile,
    KnowledgeEvidence,
)
from apps.knowledge.services import CompanyFactReviewService, CompanyProfileReviewService


def make_user(username: str):
    return get_user_model().objects.create_user(username=username)


def make_profile(organization, actor, **overrides) -> CompanyKnowledgeProfile:
    values = {
        "organization": organization,
        "brand_name": "SINOF",
        "legal_name_zh": "星沣",
        "legal_name_en": "SINOF Gear",
        "brand_aliases": ["SINOF", "星沣"],
        "internal_summary": "Internal identity only",
        "default_language": "en",
        "supported_languages": ["en", "zh-CN"],
        "primary_site_origin": "https://sinfogear.com",
        "disclosure_rules": {"public": "verified facts only"},
        "prohibited_claims": ["unverified certifications"],
        "created_by": actor,
    }
    values.update(overrides)
    return CompanyKnowledgeProfile.objects.create(**values)


def make_fact(profile, actor, **overrides) -> CompanyFact:
    values = {
        "organization": profile.organization,
        "profile": profile,
        "namespace": "company",
        "key": "brand_name",
        "value_json": {"value": "SINOF"},
        "fact_type": "TEXT",
        "visibility": CompanyFact.Visibility.PUBLIC,
        "sensitivity": CompanyFact.Sensitivity.NORMAL,
        "claim_policy": CompanyFact.ClaimPolicy.ALLOW_WITH_EVIDENCE,
        "risk_level": CompanyFact.RiskLevel.STANDARD,
        "created_by": actor,
    }
    values.update(overrides)
    return CompanyFact.objects.create(**values)


@pytest.mark.django_db
def test_company_profile_has_unique_revision_and_one_current_approved(organizations) -> None:
    organization, _ = organizations
    actor = make_user("profile-constraints")
    successor_actor = make_user("profile-successor-reviewer")
    first = make_profile(organization, actor)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_profile(organization, actor, version=first.version)

    second = make_profile(organization, actor, version=2, supersedes=first)
    service = CompanyProfileReviewService(organization)
    service.submit(first, actor=actor)
    service.approve(first, actor=actor)
    service.submit(second, actor=successor_actor)
    service.approve(second, actor=successor_actor)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == CompanyKnowledgeProfile.Status.SUPERSEDED
    assert first.reviewed_by == actor
    assert second.status == CompanyKnowledgeProfile.Status.APPROVED
    assert second.reviewed_by == successor_actor
    assert CompanyKnowledgeProfile.objects.filter(
        organization=organization,
        status=CompanyKnowledgeProfile.Status.APPROVED,
    ).count() == 1


@pytest.mark.django_db
def test_approved_profile_business_fields_and_direct_supersede_are_blocked(organizations) -> None:
    organization, _ = organizations
    actor = make_user("profile-immutable")
    profile = make_profile(organization, actor)
    service = CompanyProfileReviewService(organization)
    service.submit(profile, actor=actor)
    profile = service.approve(profile, actor=actor)

    profile.brand_name = "Changed"
    with pytest.raises(ValidationError, match="approved.*immutable"):
        profile.save()
    with pytest.raises(ValidationError, match="review service"):
        CompanyKnowledgeProfile.objects.filter(pk=profile.pk).update(
            status=CompanyKnowledgeProfile.Status.SUPERSEDED
        )


@pytest.mark.django_db
def test_profile_transition_rejects_cross_organization_service(organizations) -> None:
    own, other = organizations
    actor = make_user("profile-isolation")
    profile = make_profile(own, actor)

    with pytest.raises(ValidationError, match="organization"):
        CompanyProfileReviewService(other).submit(profile, actor=actor)


@pytest.mark.django_db
def test_company_fact_revision_identity_is_unique_and_requires_matching_profile(organizations) -> None:
    own, other = organizations
    actor = make_user("fact-identity")
    profile = make_profile(own, actor)
    foreign_profile = make_profile(other, actor)
    fact = make_fact(profile, actor)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_fact(profile, actor, version=fact.version)
    with pytest.raises(ValidationError, match="organization"):
        make_fact(foreign_profile, actor, organization=own, key="bad-profile")


@pytest.mark.django_db
def test_verified_fact_requires_a_new_revision_for_business_changes(organizations) -> None:
    organization, _ = organizations
    actor = make_user("fact-immutable")
    profile = make_profile(organization, actor)
    fact = make_fact(profile, actor)
    service = CompanyFactReviewService(organization)
    service.submit(fact, actor=actor)
    fact = service.verify(fact, actor=actor)

    fact.value_json = {"value": "Changed"}
    with pytest.raises(ValidationError, match="verified.*immutable"):
        fact.save()

    revision = service.create_revision(fact, actor=actor, value_json={"value": "Changed"})
    assert revision.version == 2
    assert revision.supersedes == fact
    assert revision.status == CompanyFact.Status.DRAFT


@pytest.mark.django_db
def test_company_fact_review_transitions_and_reject_note(organizations) -> None:
    organization, _ = organizations
    actor = make_user("fact-review")
    profile = make_profile(organization, actor)
    fact = make_fact(profile, actor)
    service = CompanyFactReviewService(organization)

    fact = service.submit(fact, actor=actor)
    assert fact.status == CompanyFact.Status.IN_REVIEW
    with pytest.raises(ValueError, match="review note"):
        service.reject(fact, actor=actor, review_note="")
    fact = service.reject(fact, actor=actor, review_note="not substantiated")
    assert fact.status == CompanyFact.Status.REJECTED
    assert fact.reviewed_by == actor
    assert fact.reviewed_at is not None


@pytest.mark.django_db
def test_fact_evidence_binding_requires_same_organization(organizations) -> None:
    own, other = organizations
    actor = make_user("binding-isolation")
    profile = make_profile(own, actor)
    fact = make_fact(profile, actor)
    foreign_evidence = KnowledgeEvidence.objects.create(
        organization=other,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        excerpt="foreign",
    )

    with pytest.raises(ValidationError, match="organization"):
        CompanyFactEvidence.objects.create(
            company_fact=fact,
            evidence=foreign_evidence,
            support_type=CompanyFactEvidence.SupportType.PRIMARY,
            citation_label="Foreign source",
            bound_by=actor,
        )


@pytest.mark.django_db
def test_fact_evidence_queryset_update_cannot_create_cross_organization_binding(organizations) -> None:
    own, other = organizations
    actor = make_user("binding-queryset-isolation")
    profile = make_profile(own, actor)
    fact = make_fact(profile, actor)
    own_evidence = KnowledgeEvidence.objects.create(
        organization=own,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        excerpt="own",
    )
    foreign_evidence = KnowledgeEvidence.objects.create(
        organization=other,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        excerpt="foreign",
    )
    binding = CompanyFactEvidence.objects.create(
        company_fact=fact,
        evidence=own_evidence,
        support_type=CompanyFactEvidence.SupportType.PRIMARY,
        citation_label="Own source",
        bound_by=actor,
    )

    with pytest.raises(ValidationError, match="organization"):
        CompanyFactEvidence.objects.filter(pk=binding.pk).update(evidence=foreign_evidence)

    binding.refresh_from_db()
    assert binding.evidence == own_evidence


@pytest.mark.django_db
def test_verified_fact_evidence_bindings_cannot_be_added_or_deleted(organizations) -> None:
    organization, _ = organizations
    actor = make_user("binding-immutable")
    profile = make_profile(organization, actor)
    fact = make_fact(profile, actor)
    evidence = KnowledgeEvidence.objects.create(
        organization=organization,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        excerpt="source",
    )
    binding = CompanyFactEvidence.objects.create(
        company_fact=fact,
        evidence=evidence,
        support_type=CompanyFactEvidence.SupportType.PRIMARY,
        citation_label="Source",
        bound_by=actor,
    )
    service = CompanyFactReviewService(organization)
    service.submit(fact, actor=actor)
    fact = service.verify(fact, actor=actor)

    with pytest.raises(ValidationError, match="verified"):
        CompanyFactEvidence.objects.create(
            company_fact=fact,
            evidence=evidence,
            support_type=CompanyFactEvidence.SupportType.SUPPORTING,
            citation_label="Second binding",
            bound_by=actor,
        )
    with pytest.raises(ValidationError, match="verified"):
        binding.delete()
    with pytest.raises(ValidationError, match="verified"):
        CompanyFactEvidence.objects.filter(pk=binding.pk).delete()


@pytest.mark.django_db
def test_knowledge_evidence_extension_defaults_are_conservative(organizations) -> None:
    evidence = KnowledgeEvidence.objects.create(
        organization=organizations[0],
        evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
        excerpt="legacy-shaped evidence",
    )

    assert evidence.usage_rights == KnowledgeEvidence.UsageRights.UNKNOWN
    assert evidence.sensitivity == KnowledgeEvidence.Sensitivity.NORMAL
    assert evidence.is_demo is False
    assert evidence.content_hash == ""
    assert evidence.expires_at is None
    assert evidence.review_note == ""


@pytest.mark.django_db
@pytest.mark.parametrize("write_style", ["queryset", "bulk"])
def test_verified_fact_business_fields_cannot_be_changed_through_bulk_paths(
    organizations, write_style
) -> None:
    organization, _ = organizations
    actor = make_user(f"fact-bulk-{write_style}")
    profile = make_profile(organization, actor)
    fact = make_fact(profile, actor)
    service = CompanyFactReviewService(organization)
    service.submit(fact, actor=actor)
    fact = service.verify(fact, actor=actor)

    with pytest.raises(ValidationError, match="verified.*immutable"):
        if write_style == "queryset":
            CompanyFact.objects.filter(pk=fact.pk).update(value_json={"value": "bypass"})
        else:
            fact.value_json = {"value": "bypass"}
            CompanyFact.objects.bulk_update([fact], ["value_json"])

    fact.refresh_from_db()
    assert fact.value_json == {"value": "SINOF"}


@pytest.mark.django_db
def test_verified_fact_binding_cannot_be_updated_through_queryset(organizations) -> None:
    organization, _ = organizations
    actor = make_user("binding-update")
    profile = make_profile(organization, actor)
    fact = make_fact(profile, actor)
    evidence = KnowledgeEvidence.objects.create(
        organization=organization,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        excerpt="source",
    )
    binding = CompanyFactEvidence.objects.create(
        company_fact=fact,
        evidence=evidence,
        support_type=CompanyFactEvidence.SupportType.PRIMARY,
        citation_label="Original",
        bound_by=actor,
    )
    service = CompanyFactReviewService(organization)
    service.submit(fact, actor=actor)
    service.verify(fact, actor=actor)

    with pytest.raises(ValidationError, match="verified"):
        CompanyFactEvidence.objects.filter(pk=binding.pk).update(citation_label="Bypass")


@pytest.mark.django_db
def test_verifying_new_fact_revision_supersedes_previous_verified_revision(organizations) -> None:
    organization, _ = organizations
    actor = make_user("fact-supersede")
    profile = make_profile(organization, actor)
    service = CompanyFactReviewService(organization)
    first = make_fact(profile, actor)
    service.submit(first, actor=actor)
    first = service.verify(first, actor=actor)
    second = service.create_revision(first, actor=actor, value_json={"value": "SINOF Gear"})
    service.submit(second, actor=actor)
    second = service.verify(second, actor=actor)

    first.refresh_from_db()
    assert first.status == CompanyFact.Status.SUPERSEDED
    assert second.status == CompanyFact.Status.VERIFIED
    assert CompanyFact.objects.filter(
        profile=profile,
        namespace="company",
        key="brand_name",
        status=CompanyFact.Status.VERIFIED,
    ).count() == 1
