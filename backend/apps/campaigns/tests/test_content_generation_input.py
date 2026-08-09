import json
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from apps.assets.models import AssetProductLink, MaterialAsset
from apps.campaigns.models import Campaign, ContentBriefConceptLink
from apps.campaigns.services import (
    build_content_generation_input,
    create_content_brief,
    mark_content_brief_ready,
    revise_content_brief,
)
from apps.catalog.models import Product
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeGraphLock,
    KnowledgeRelation,
)
from apps.knowledge.guards import _test_fixture_writes
from apps.platforms.models import Platform

from .conftest import (
    make_asset,
    make_concept,
    make_platform,
    make_product,
    valid_brief_values,
)


def make_ready_brief(organization, user):
    product = make_product(organization)
    platform = make_platform()
    concept = make_concept(
        organization, concept_type="INDUSTRY", code="PRECISION_ENGINEERING"
    )
    asset = make_asset(organization, user)
    AssetProductLink.objects.create(
        organization=organization, asset=asset, product=product
    )
    campaign = Campaign.objects.create(organization=organization, name="Launch")
    brief = create_content_brief(
        organization=organization,
        campaign=campaign,
        creator=user,
        values=valid_brief_values(),
        product_ids=[product.id],
        asset_ids=[asset.id],
        platform_ids=[platform.id],
        concept_links=[{"role": "TARGET_INDUSTRY", "concept_id": concept.id}],
    )
    return (
        mark_content_brief_ready(brief.id, reviewer=user),
        campaign,
        product,
        asset,
        platform,
        concept,
    )


@pytest.mark.django_db
def test_revision_is_new_draft_and_preserves_ready_source(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, product, asset, platform, concept = make_ready_brief(own, campaign_user)

    revision = revise_content_brief(ready.id, creator=campaign_user)
    ready.refresh_from_db()

    assert ready.status == "READY"
    assert revision.status == "DRAFT"
    assert revision.previous_version_id == ready.id
    assert revision.version == ready.version + 1
    assert set(revision.product_links.values_list("product_id", flat=True)) == {product.id}
    assert set(revision.asset_links.values_list("asset_id", flat=True)) == {asset.id}
    assert set(revision.platform_links.values_list("platform_id", flat=True)) == {platform.id}
    assert set(revision.concept_links.values_list("concept_id", flat=True)) == {concept.id}


@pytest.mark.django_db
def test_generation_input_is_complete_frozen_and_json_serializable(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, campaign, product, asset, platform, concept = make_ready_brief(
        own, campaign_user
    )

    snapshot = build_content_generation_input(ready.id)
    before = snapshot.to_dict()

    Product.objects.filter(pk=product.id).update(name_en="Changed later")
    MaterialAsset.objects.filter(pk=asset.id).update(tags=["changed"])
    Platform.objects.filter(pk=platform.id).update(name="Changed later")
    KnowledgeConcept.objects.filter(pk=concept.id).update(label_en="Changed later")

    assert snapshot.organization_id == own.id
    assert snapshot.brief_id == ready.id
    assert snapshot.campaign_id == campaign.id
    assert snapshot.products[0].name_en == "Precision gear"
    assert snapshot.assets[0].checksum == "a" * 64
    assert snapshot.assets[0].product_ids == (product.id,)
    assert snapshot.target_platforms[0].capability_codes == ("PUBLISH",)
    assert {item.concept_id for item in snapshot.ontology_snapshot.concept_versions} == {
        concept.id
    }
    assert snapshot.to_dict() == before
    assert "storage_key" not in before["assets"][0]
    json.dumps(before)


@pytest.mark.django_db
def test_generation_input_fails_closed_for_draft_or_corrupted_live_reference(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    draft_campaign = Campaign.objects.create(organization=own, name="Draft")
    draft = create_content_brief(
        organization=own,
        campaign=draft_campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[],
        asset_ids=[],
        platform_ids=[],
        concept_links=[],
    )
    with pytest.raises(ValidationError, match="READY"):
        build_content_generation_input(draft.id)

    ready, _, _, _, _, concept = make_ready_brief(own, campaign_user)
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.id).update(status="DEPRECATED")

    with pytest.raises(ValidationError, match="approved"):
        build_content_generation_input(ready.id)


@pytest.mark.django_db
def test_ready_relation_rows_cannot_be_mutated_or_deleted(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, _, _, _, _ = make_ready_brief(own, campaign_user)
    link = ContentBriefConceptLink.objects.get(brief=ready)

    with pytest.raises(ValidationError, match="immutable"):
        ContentBriefConceptLink.objects.filter(pk=link.pk).update(role="APPLICATION")
    with pytest.raises(Exception):
        ContentBriefConceptLink.objects.filter(pk=link.pk).delete()


@pytest.mark.django_db
def test_generation_snapshot_locks_expanded_ontology_rows_and_evidence_associations(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    ready, _, _, _, _, root = make_ready_brief(own, campaign_user)
    target = make_concept(
        own, concept_type="PURCHASE_INTENT", code="LOCKED_EXPANSION"
    )
    with _test_fixture_writes():
        relation = KnowledgeRelation.objects.create(
            organization=own,
            subject_concept=root,
            predicate="INDICATES_PURCHASE_INTENT",
            object_concept=target,
            status="APPROVED",
        )
        evidence = KnowledgeEvidence.objects.create(
            organization=own,
            evidence_type="HUMAN_ENTRY",
            excerpt="Locked evidence",
            status="APPROVED",
        )
    root.evidence.add(evidence)
    relation.evidence.add(evidence)
    concept_through = KnowledgeConcept.evidence.through
    relation_through = KnowledgeRelation.evidence.through

    managers = [
        KnowledgeGraphLock.objects,
        KnowledgeConcept.objects,
        KnowledgeRelation.objects,
        KnowledgeEvidence.objects,
        concept_through.objects,
        relation_through.objects,
    ]
    patches = [
        patch.object(manager, "select_for_update", wraps=manager.select_for_update)
        for manager in managers
    ]
    mocks = [item.start() for item in patches]
    try:
        snapshot = build_content_generation_input(ready.id)
    finally:
        for item in reversed(patches):
            item.stop()

    assert {item.concept_id for item in snapshot.ontology_snapshot.concept_versions} >= {
        root.id,
        target.id,
    }
    assert all(mock.called for mock in mocks)
