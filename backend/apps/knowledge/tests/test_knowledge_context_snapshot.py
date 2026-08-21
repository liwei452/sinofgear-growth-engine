from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.models import Product
from apps.growth.models import GrowthMission, MissionPlan
from apps.knowledge.context_builder import (
    CatalogProductContextAdapter,
    KnowledgeContextBuildError,
    KnowledgeContextBuilder,
    build_mission_context,
)
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    CompanyFact,
    CompanyFactEvidence,
    CompanyKnowledgeProfile,
    ICPProductLink,
    ICPProfile,
    KnowledgeContextSnapshot,
    KnowledgeEvidence,
    KnowledgeStatus,
    WebsitePage,
    WebsitePageConceptLink,
    WebsitePageProductLink,
)

from .conftest import make_concept
from .test_icp_profile_foundation import make_product


def make_actor(label: str):
    return get_user_model().objects.create_user(username=f"snapshot-{label}-{uuid4().hex[:8]}")


def make_mission(organization, actor, product, **overrides) -> GrowthMission:
    values = {
        "organization": organization,
        "title": "Export pilot",
        "objective": "Generate qualified sourcing conversations",
        "target_countries": ["DE"],
        "target_industries": ["Industrial equipment"],
        "customer_profile": "OEM procurement teams",
        "primary_product": product,
        "start_date": date(2026, 8, 21),
        "end_date": date(2026, 9, 21),
        "target_account_count": 20,
        "target_reply_count": 4,
        "target_rfq_count": 2,
        "budget_micros": 1_500_000,
        "allowed_channels": ["EMAIL"],
        "attribution_code": f"snapshot-{uuid4().hex[:12]}",
        "created_by": actor,
    }
    values.update(overrides)
    return GrowthMission.objects.create(**values)


def make_approved_profile(organization, actor, **overrides) -> CompanyKnowledgeProfile:
    values = {
        "organization": organization,
        "brand_name": "Example Manufacturing",
        "brand_aliases": ["Example"],
        "internal_summary": "A contract manufacturer.",
        "default_language": "en",
        "supported_languages": ["en"],
        "primary_site_origin": "https://example.test/",
        "disclosure_rules": {"external": "verified facts only"},
        "prohibited_claims": ["Do not claim unverified certifications"],
        "status": CompanyKnowledgeProfile.Status.APPROVED,
        "created_by": actor,
        "reviewed_by": actor,
        "reviewed_at": timezone.now(),
    }
    values.update(overrides)
    with _test_fixture_writes():
        return CompanyKnowledgeProfile.objects.create(**values)


def make_approved_icp(organization, actor, product, *, code="OEM", **overrides) -> ICPProfile:
    values = {
        "organization": organization,
        "code": code,
        "name": f"{code} buyers",
        "description": "Qualified procurement teams.",
        "target_industries": ["Industrial equipment"],
        "company_types": ["OEM"],
        "buyer_roles": ["Procurement"],
        "target_markets": ["DE"],
        "languages": ["en"],
        "pain_points": ["Lead time"],
        "buying_triggers": ["New program"],
        "exclusion_rules": ["No active project"],
        "preferred_channels": ["Email"],
        "created_by": actor,
    }
    values.update(overrides)
    profile = ICPProfile.objects.create(**values)
    ICPProductLink.objects.create(
        icp_profile=profile,
        product=product,
        role=ICPProductLink.Role.PRIMARY,
        priority=1,
        use_cases=["Supplier qualification"],
    )
    with _test_fixture_writes():
        ICPProfile.objects.filter(pk=profile.pk).update(
            status=ICPProfile.Status.APPROVED,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
    profile.refresh_from_db()
    return profile


def make_context_sources(organizations):
    organization, other = organizations
    actor = make_actor("sources")
    product = make_product(organization, name="Product A")
    mission = make_mission(organization, actor, product)
    company_profile = make_approved_profile(organization, actor)
    icp = make_approved_icp(organization, actor, product)
    return organization, other, actor, product, mission, company_profile, icp


def make_fact(
    profile,
    actor,
    *,
    key,
    value,
    claim_policy=CompanyFact.ClaimPolicy.ALLOW_WITH_EVIDENCE,
    sensitivity=CompanyFact.Sensitivity.NORMAL,
    visibility=CompanyFact.Visibility.PUBLIC,
    is_demo=False,
) -> CompanyFact:
    with _test_fixture_writes():
        return CompanyFact.objects.create(
            organization=profile.organization,
            profile=profile,
            namespace="company",
            key=key,
            value_json=value,
            fact_type="TEXT",
            status=CompanyFact.Status.VERIFIED,
            visibility=visibility,
            sensitivity=sensitivity,
            claim_policy=claim_policy,
            is_demo=is_demo,
            created_by=actor,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )


def bind_public_evidence(fact, actor, *, excerpt="Approved public source"):
    with _test_fixture_writes():
        evidence = KnowledgeEvidence.objects.create(
            organization=fact.organization,
            evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
            source_url="https://evidence.example.test/source",
            excerpt=excerpt,
            captured_at=timezone.now(),
            content_hash="a" * 64,
            usage_rights=KnowledgeEvidence.UsageRights.PUBLIC,
            sensitivity=KnowledgeEvidence.Sensitivity.NORMAL,
            status=KnowledgeStatus.APPROVED,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
        return CompanyFactEvidence.objects.create(
            company_fact=fact,
            evidence=evidence,
            support_type=CompanyFactEvidence.SupportType.PRIMARY,
            citation_label="Public source",
            bound_by=actor,
        )


def assert_error_code(expected_code, callable_):
    with pytest.raises(KnowledgeContextBuildError) as caught:
        callable_()
    assert caught.value.code == expected_code


@pytest.mark.django_db
def test_builder_rejects_foreign_mission_and_requires_approved_profile(organizations) -> None:
    organization, other = organizations
    actor = make_actor("organization")
    product = make_product(organization, name="Product A")
    mission = make_mission(organization, actor, product)

    assert_error_code(
        "ORGANIZATION_MISMATCH",
        lambda: build_mission_context(organization=other, mission=mission, actor=actor),
    )
    assert_error_code(
        "COMPANY_PROFILE_REQUIRED",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )


@pytest.mark.django_db
def test_builder_rejects_stale_cross_organization_primary_product(organizations) -> None:
    organization, other = organizations
    actor = make_actor("foreign-product")
    product = make_product(organization, name="Product A")
    foreign_product = make_product(other, name="Foreign Product")
    mission = make_mission(organization, actor, product)
    make_approved_profile(organization, actor)
    make_approved_icp(organization, actor, product)
    GrowthMission.objects.filter(pk=mission.pk).update(primary_product=foreign_product)

    assert_error_code(
        "ORGANIZATION_MISMATCH",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )


@pytest.mark.django_db
def test_icp_auto_selection_requires_exactly_one_match(organizations) -> None:
    organization, _ = organizations
    actor = make_actor("icp-selection")
    product = make_product(organization, name="Product A")
    mission = make_mission(organization, actor, product)
    make_approved_profile(organization, actor)

    assert_error_code(
        "ICP_CONFIGURATION_REQUIRED",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )
    selected = make_approved_icp(organization, actor, product, code="ONLY")
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    assert snapshot.payload["icp_profiles"][0]["id"] == str(selected.id)

    make_approved_icp(organization, actor, product, code="SECOND")
    assert_error_code(
        "ICP_SELECTION_REQUIRED",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )


@pytest.mark.django_db
def test_explicit_icp_ids_are_native_unique_approved_product_matches(organizations) -> None:
    organization, other, actor, product, mission, _, icp = make_context_sources(organizations)
    foreign_product = make_product(other, name="Foreign Product")
    foreign = make_approved_icp(other, actor, foreign_product, code="FOREIGN")

    for invalid_ids in ([str(icp.id)], [icp.id, icp.id], (icp.id,), [foreign.id], [uuid4()]):
        assert_error_code(
            "INVALID_ICP_SELECTION",
            lambda invalid_ids=invalid_ids: build_mission_context(
                organization=organization,
                mission=mission,
                actor=actor,
                icp_profile_ids=invalid_ids,
            ),
        )


@pytest.mark.django_db
def test_public_claim_contains_only_eligible_fact_and_safe_citation(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    eligible = make_fact(profile, actor, key="qualified", value={"text": "Qualified claim"})
    binding = bind_public_evidence(eligible, actor)
    make_fact(
        profile,
        actor,
        key="unqualified",
        value={"text": "No evidence claim"},
    )

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    claims = snapshot.payload["company"]["public_claims"]
    assert [claim["fact_id"] for claim in claims] == [str(eligible.id)]
    assert "No evidence claim" not in snapshot.canonical_payload
    assert claims[0]["evidence"][0] == {
        "evidence_id": str(binding.evidence_id),
        "evidence_type": KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        "source_url": "https://evidence.example.test/source",
        "excerpt": "Approved public source",
        "content_hash": "a" * 64,
        "captured_at": binding.evidence.captured_at.isoformat(),
    }


@pytest.mark.django_db
def test_stale_cross_organization_evidence_cannot_support_public_claim(organizations) -> None:
    organization, other, actor, _, mission, profile, _ = make_context_sources(organizations)
    fact = make_fact(profile, actor, key="foreign-evidence", value={"text": "Blocked claim"})
    binding = bind_public_evidence(fact, actor, excerpt="FOREIGN-EVIDENCE-SENTINEL")
    with _test_fixture_writes():
        KnowledgeEvidence.objects.filter(pk=binding.evidence_id).update(organization=other)

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    assert snapshot.payload["company"]["public_claims"] == []
    assert "FOREIGN-EVIDENCE-SENTINEL" not in snapshot.canonical_payload
    assert snapshot.payload["company"]["excluded_summary"]["by_reason"] == {
        "MISSING_PUBLIC_EVIDENCE": 1
    }


@pytest.mark.django_db
def test_sensitive_and_never_send_fact_values_do_not_enter_serialized_payload(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    secrets = {
        CompanyFact.ClaimPolicy.NEVER_SEND_TO_MODEL: "NEVER-SENTINEL",
        CompanyFact.Sensitivity.CONFIDENTIAL: "CONFIDENTIAL-SENTINEL",
        CompanyFact.Sensitivity.SECRET: "SECRET-SENTINEL",
    }
    make_fact(
        profile,
        actor,
        key="never",
        value={"secret": secrets[CompanyFact.ClaimPolicy.NEVER_SEND_TO_MODEL]},
        claim_policy=CompanyFact.ClaimPolicy.NEVER_SEND_TO_MODEL,
    )
    for sensitivity in (CompanyFact.Sensitivity.CONFIDENTIAL, CompanyFact.Sensitivity.SECRET):
        make_fact(
            profile,
            actor,
            key=sensitivity.lower(),
            value={"secret": secrets[sensitivity]},
            sensitivity=sensitivity,
        )

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    serialized = snapshot.canonical_payload
    assert all(secret not in serialized for secret in secrets.values())
    assert snapshot.payload["company"]["excluded_summary"]["total"] == 3


@pytest.mark.django_db
def test_excluded_fact_total_counts_facts_not_blocking_reasons(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    make_fact(
        profile,
        actor,
        key="multi-blocked",
        value={"secret": "MULTI-BLOCKED-SENTINEL"},
        sensitivity=CompanyFact.Sensitivity.SECRET,
        is_demo=True,
    )

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    summary = snapshot.payload["company"]["excluded_summary"]

    assert summary["total"] == 1
    assert summary["by_reason"] == {"FACT_IS_DEMO": 1, "SECRET": 1}


@pytest.mark.django_db
def test_internal_context_is_normal_current_and_never_externally_allowed(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    internal = make_fact(
        profile,
        actor,
        key="internal",
        value={"text": "Internal capability"},
        claim_policy=CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY,
        visibility=CompanyFact.Visibility.INTERNAL,
    )

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    assert snapshot.payload["company"]["internal_context"] == [
        {
            "fact_id": str(internal.id),
            "namespace": "company",
            "key": "internal",
            "version": 1,
            "value": {"text": "Internal capability"},
            "valid_from": None,
            "valid_until": None,
            "external_use_allowed": False,
        }
    ]


@pytest.mark.django_db
def test_product_adapter_is_an_independent_builder_dependency(organizations) -> None:
    organization, _, actor, _, mission, _, _ = make_context_sources(organizations)

    class ProductAdapterStub(CatalogProductContextAdapter):
        def serialize(self, product, *, concept_links=None):
            return {"id": str(product.id), "technical_attributes": {"adapter": "stub"}}

    snapshot = KnowledgeContextBuilder(product_adapter=ProductAdapterStub()).build_mission_context(
        organization=organization,
        mission=mission,
        actor=actor,
    )

    assert snapshot.payload["product"]["technical_attributes"] == {"adapter": "stub"}


@pytest.mark.django_db
def test_latest_approved_plan_is_selected(organizations) -> None:
    organization, _, actor, _, mission, _, _ = make_context_sources(organizations)
    for version in (1, 3, 2):
        MissionPlan.objects.create(
            organization=organization,
            mission=mission,
            version=version,
            status=MissionPlan.Status.APPROVED,
            snapshot={"version": version},
            generation_mode=MissionPlan.GenerationMode.AUTOMATION,
            created_by=actor,
            approved_by=actor,
            approved_at=timezone.now(),
        )

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    assert snapshot.mission_plan.version == 3
    assert snapshot.payload["mission"]["plan"]["version"] == 3


@pytest.mark.django_db
def test_website_selection_includes_valid_pages_and_summarizes_invalid_pages(organizations) -> None:
    organization, _, actor, product, mission, _, _ = make_context_sources(organizations)
    valid = WebsitePage.objects.create(
        organization=organization,
        canonical_url="https://example.test/product",
        page_type=WebsitePage.PageType.PRODUCT,
        language="en",
        title="Product page",
        content_summary="Product information",
        primary_cta_label="Request quote",
        primary_cta_url="https://example.test/rfq#form",
        seo_keywords=["product"],
        source_type=WebsitePage.SourceType.MANUAL,
        created_by=actor,
    )
    WebsitePageProductLink.objects.create(
        website_page=valid,
        product=product,
        relation_type=WebsitePageProductLink.RelationType.PRIMARY,
    )
    invalid = WebsitePage.objects.create(
        organization=organization,
        canonical_url="https://example.test/about",
        page_type=WebsitePage.PageType.ABOUT,
        language="en",
        title="About",
        seo_keywords=[],
        source_type=WebsitePage.SourceType.MANUAL,
        created_by=actor,
    )
    concept = make_concept(
        code="APPLICATION_PAGE",
        concept_type="APPLICATION",
        organization=organization,
    )
    WebsitePageConceptLink.objects.create(
        website_page=invalid,
        concept=concept,
        role=WebsitePageConceptLink.Role.APPLICATION,
    )
    with _test_fixture_writes():
        WebsitePage.objects.filter(pk__in=[valid.pk, invalid.pk]).update(
            status=WebsitePage.Status.VERIFIED,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
        type(concept).objects.filter(pk=concept.pk).update(status=KnowledgeStatus.DEPRECATED)

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    assert [page["page_id"] for page in snapshot.payload["website_pages"]] == [str(valid.id)]
    assert snapshot.payload["website_pages"][0]["primary_cta"]["url"].endswith("#form")
    assert snapshot.payload["website_excluded_summary"]["total"] == 1
    assert "CONCEPT_NOT_APPROVED" in snapshot.payload["website_excluded_summary"]["by_reason"]


@pytest.mark.django_db
def test_canonical_hashes_are_deterministic_and_source_change_creates_snapshot(organizations) -> None:
    organization, _, actor, _, mission, _, _ = make_context_sources(organizations)

    first = build_mission_context(organization=organization, mission=mission, actor=actor)
    repeated = build_mission_context(organization=organization, mission=mission, actor=actor)
    assert repeated.pk == first.pk
    assert repeated.payload_hash == first.payload_hash
    assert repeated.payload_size_bytes == len(repeated.canonical_payload.encode("utf-8"))

    mission.objective = "A changed deterministic objective"
    mission.save(update_fields=["objective"])
    changed = build_mission_context(organization=organization, mission=mission, actor=actor)
    assert changed.pk != first.pk
    assert changed.source_fingerprint != first.source_fingerprint


@pytest.mark.django_db
def test_snapshot_is_append_only_for_all_mutation_paths(organizations) -> None:
    organization, _, actor, _, mission, _, _ = make_context_sources(organizations)
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    snapshot.builder_version = "changed"
    with pytest.raises(ValidationError, match="append-only"):
        snapshot.save()
    with pytest.raises(ValidationError, match="append-only"):
        KnowledgeContextSnapshot.objects.filter(pk=snapshot.pk).update(builder_version="changed")
    with pytest.raises(ValidationError, match="append-only"):
        KnowledgeContextSnapshot.objects.bulk_update([snapshot], ["builder_version"])
    with pytest.raises(ValidationError, match="append-only"):
        snapshot.delete()
    with pytest.raises(ValidationError, match="append-only"):
        KnowledgeContextSnapshot.objects.filter(pk=snapshot.pk).delete()
    with pytest.raises(ValidationError, match="snapshot service"):
        KnowledgeContextSnapshot.objects.bulk_create([snapshot])


@pytest.mark.django_db
def test_credential_shaped_profile_data_is_rejected_before_persistence(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    with _test_fixture_writes():
        CompanyKnowledgeProfile.objects.filter(pk=profile.pk).update(
            disclosure_rules={"credential_reference": "vault://forbidden"}
        )

    assert_error_code(
        "UNSAFE_CONTEXT_SOURCE",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )
    assert KnowledgeContextSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_payload_over_total_limit_is_not_persisted(organizations) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    with _test_fixture_writes():
        CompanyKnowledgeProfile.objects.filter(pk=profile.pk).update(
            prohibited_claims=["x" * (513 * 1024)]
        )

    assert_error_code(
        "CONTEXT_TOO_LARGE",
        lambda: build_mission_context(organization=organization, mission=mission, actor=actor),
    )
    assert KnowledgeContextSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_section_limits_are_stable_and_record_omitted_counts(organizations, monkeypatch) -> None:
    organization, _, actor, _, mission, profile, _ = make_context_sources(organizations)
    for index in range(3):
        make_fact(
            profile,
            actor,
            key=f"internal-{index}",
            value={"index": index},
            claim_policy=CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY,
            visibility=CompanyFact.Visibility.INTERNAL,
        )
    monkeypatch.setattr("apps.knowledge.context_builder.MAX_INTERNAL_CONTEXT", 2)

    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    assert len(snapshot.payload["company"]["internal_context"]) == 2
    assert snapshot.payload["truncation"]["internal_context"] == {
        "limit": 2,
        "omitted_count": 1,
    }


def test_adapter_uses_fixed_decimal_and_uuid_strings() -> None:
    adapter = CatalogProductContextAdapter()
    product = Product(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        version=2,
        name_en="Product",
        status=Product.Status.ACTIVE,
        module_min=Decimal("1.2500"),
        module_max=Decimal("2.5000"),
        tooth_count_min=10,
        tooth_count_max=20,
        pressure_angle=Decimal("20.000"),
        moq=1,
        manufacturing_capabilities=[],
        inspection_capabilities=[],
    )

    payload = adapter.serialize(product, concept_links=[])

    assert payload["id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["technical_attributes"]["module_min"] == "1.2500"
