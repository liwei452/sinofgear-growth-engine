import json

import pytest
from django.db import connection
from django.utils import timezone

from apps.knowledge.agent_context import (
    AgentContextPurpose,
    KnowledgeContextError,
    load_agent_context,
    validate_external_output,
)
from apps.knowledge.context_builder import build_mission_context
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import CompanyFact, WebsitePage, WebsitePageProductLink

from .test_knowledge_context_snapshot import (
    bind_public_evidence,
    make_context_sources,
    make_fact,
)


def _assert_code(code, callable_):
    with pytest.raises(KnowledgeContextError) as caught:
        callable_()
    assert caught.value.code == code
    assert "token" not in repr(caught.value).lower()


def _verified_page(organization, actor, product):
    page = WebsitePage.objects.create(
        organization=organization,
        canonical_url="https://example.test/products/a",
        page_type=WebsitePage.PageType.PRODUCT,
        language="en",
        title="Product A",
        content_summary="Public product page",
        primary_cta_label="Request quote",
        primary_cta_url="https://example.test/rfq#a",
        seo_keywords=["precision", "oem"],
        source_type=WebsitePage.SourceType.MANUAL,
        created_by=actor,
    )
    WebsitePageProductLink.objects.create(
        website_page=page,
        product=product,
        relation_type=WebsitePageProductLink.RelationType.PRIMARY,
    )
    with _test_fixture_writes():
        WebsitePage.objects.filter(pk=page.pk).update(
            status=WebsitePage.Status.VERIFIED,
            reviewed_by=actor,
            reviewed_at=timezone.now(),
        )
    return page


@pytest.mark.django_db
def test_purpose_projection_separates_public_internal_and_preserves_citation(organizations):
    organization, _, actor, product, mission, profile, _ = make_context_sources(organizations)
    public = make_fact(profile, actor, key="capacity", value={"text": "Public capacity"})
    citation = bind_public_evidence(public, actor, excerpt="Public citation")
    internal = make_fact(
        profile,
        actor,
        key="margin",
        value={"text": "Internal margin"},
        claim_policy=CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY,
        visibility=CompanyFact.Visibility.INTERNAL,
    )
    _verified_page(organization, actor, product)
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)

    context = load_agent_context(
        organization=organization,
        mission=mission,
        snapshot_id=snapshot.id,
    )
    lead = context.for_purpose(AgentContextPurpose.LEAD_JUDGMENT).to_dict()
    outreach = context.for_purpose(AgentContextPurpose.OUTREACH).to_dict()

    assert context.provenance == {
        "knowledge_context_snapshot_id": str(snapshot.id),
        "payload_hash": snapshot.payload_hash,
        "schema_version": snapshot.schema_version,
        "builder_version": snapshot.builder_version,
    }
    assert lead["seller"]["internal_context"][0]["fact_id"] == str(internal.id)
    assert "internal_context" not in outreach["seller"]
    assert "internal_summary" not in outreach["seller"]["company_profile"]
    assert "primary_site_origin" not in outreach["seller"]["company_profile"]
    assert outreach["seller"]["public_claims"][0]["fact_id"] == str(public.id)
    assert outreach["seller"]["public_claims"][0]["evidence"][0] == {
        "evidence_id": str(citation.evidence_id),
        "evidence_type": "PUBLIC_SOURCE",
        "source_url": "https://evidence.example.test/source",
        "excerpt": "Public citation",
        "content_hash": "a" * 64,
        "captured_at": citation.evidence.captured_at.isoformat(),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("mismatch", ["organization", "mission", "product"])
def test_load_rejects_tenant_mission_and_product_mismatch(organizations, mismatch):
    organization, other, actor, product, mission, _, _ = make_context_sources(organizations)
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    if mismatch == "organization":
        kwargs = {"organization": other, "mission": mission}
    elif mismatch == "mission":
        _, _, _, _, other_mission, _, _ = make_context_sources((other, organization))
        kwargs = {"organization": organization, "mission": other_mission}
    else:
        original = mission.primary_product_id
        mission.primary_product_id = other.id
        kwargs = {"organization": organization, "mission": mission}
        mission.primary_product_id = original
        # Give the consumer an in-memory Mission whose declared product differs.
        mission.primary_product_id = other.id
    _assert_code(
        "KNOWLEDGE_CONTEXT_MISMATCH",
        lambda: load_agent_context(snapshot_id=snapshot.id, **kwargs),
    )


@pytest.mark.django_db
def test_load_rejects_tampered_hash_and_unsafe_nested_key(organizations):
    organization, _, actor, _, mission, _, _ = make_context_sources(organizations)
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE knowledge_knowledgecontextsnapshot SET payload_hash = %s WHERE id = %s",
            ["0" * 64, snapshot.id.hex],
        )
    _assert_code(
        "KNOWLEDGE_CONTEXT_CORRUPT",
        lambda: load_agent_context(
            organization=organization, mission=mission, snapshot_id=snapshot.id
        ),
    )

    payload = dict(snapshot.payload)
    payload["company"] = {**payload["company"], "nested": {"api_key": "TOKEN-SENTINEL"}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    payload_hash = hashlib.sha256(encoded.encode()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE knowledge_knowledgecontextsnapshot SET payload = %s, payload_hash = %s, payload_size_bytes = %s WHERE id = %s",
            [encoded, payload_hash, len(encoded.encode()), snapshot.id.hex],
        )
    _assert_code(
        "KNOWLEDGE_CONTEXT_CORRUPT",
        lambda: load_agent_context(
            organization=organization, mission=mission, snapshot_id=snapshot.id
        ),
    )


@pytest.mark.django_db
def test_outreach_requires_verified_landing_page_and_validates_external_output(organizations):
    organization, _, actor, product, mission, profile, _ = make_context_sources(organizations)
    public = make_fact(profile, actor, key="quality", value={"text": "Verified quality"})
    bind_public_evidence(public, actor)
    internal = make_fact(
        profile,
        actor,
        key="internal",
        value={"text": "Private"},
        claim_policy=CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY,
        visibility=CompanyFact.Visibility.INTERNAL,
    )
    without_page = build_mission_context(
        organization=organization, mission=mission, actor=actor
    )
    context = load_agent_context(
        organization=organization, mission=mission, snapshot_id=without_page.id
    )
    _assert_code(
        "VERIFIED_LANDING_PAGE_REQUIRED",
        lambda: context.for_purpose(AgentContextPurpose.OUTREACH),
    )

    page = _verified_page(organization, actor, product)
    snapshot = build_mission_context(organization=organization, mission=mission, actor=actor)
    context = load_agent_context(
        organization=organization, mission=mission, snapshot_id=snapshot.id
    )
    outreach = context.for_purpose(AgentContextPurpose.OUTREACH)
    valid = {
        "draft": "A careful public note",
        "cited_fact_ids": [str(public.id)],
        "landing_page_url": page.primary_cta_url,
    }
    assert validate_external_output(valid, context=outreach) == valid
    _assert_code(
        "PUBLIC_CLAIM_BLOCKED",
        lambda: validate_external_output(
            {**valid, "cited_fact_ids": [str(internal.id)]}, context=outreach
        ),
    )
    _assert_code(
        "VERIFIED_LANDING_PAGE_REQUIRED",
        lambda: validate_external_output(
            {**valid, "landing_page_url": "https://example.test/guessed"},
            context=outreach,
        ),
    )
    _assert_code(
        "PUBLIC_CLAIM_BLOCKED",
        lambda: validate_external_output(
            {**valid, "draft": "Do not claim unverified certifications"},
            context=outreach,
        ),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["title", "hook", "cta", "subject"])
def test_external_output_scans_every_outbound_text_field(organizations, field):
    organization, _, actor, product, mission, profile, _ = make_context_sources(
        organizations
    )
    public = make_fact(profile, actor, key="quality", value={"text": "Verified quality"})
    bind_public_evidence(public, actor)
    page = _verified_page(organization, actor, product)
    snapshot = build_mission_context(
        organization=organization, mission=mission, actor=actor
    )
    context = load_agent_context(
        organization=organization, mission=mission, snapshot_id=snapshot.id
    ).for_purpose(AgentContextPurpose.OUTREACH)
    valid = {
        "draft": "A short technical review may be useful.",
        "cited_fact_ids": [str(public.id)],
        "landing_page_url": page.primary_cta_url,
    }

    _assert_code(
        "PUBLIC_CLAIM_BLOCKED",
        lambda: validate_external_output(
            {**valid, field: "Do not claim unverified certifications"},
            context=context,
        ),
    )
    _assert_code(
        "VERIFIED_LANDING_PAGE_REQUIRED",
        lambda: validate_external_output(
            {**valid, field: "Review https://attacker.example/offer"},
            context=context,
        ),
    )


@pytest.mark.django_db
def test_external_output_requires_at_least_one_public_fact_citation(organizations):
    organization, _, actor, product, mission, _, _ = make_context_sources(organizations)
    page = _verified_page(organization, actor, product)
    snapshot = build_mission_context(
        organization=organization, mission=mission, actor=actor
    )
    context = load_agent_context(
        organization=organization, mission=mission, snapshot_id=snapshot.id
    ).for_purpose(AgentContextPurpose.OUTREACH)

    _assert_code(
        "PUBLIC_CLAIM_BLOCKED",
        lambda: validate_external_output(
            {
                "draft": "A short technical review may be useful.",
                "cited_fact_ids": [],
                "landing_page_url": page.primary_cta_url,
            },
            context=context,
        ),
    )
