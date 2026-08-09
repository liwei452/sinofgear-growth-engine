import uuid

import pytest
from django.core.exceptions import ValidationError
from unittest.mock import patch

from apps.campaigns.models import (
    Campaign,
    CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
)

from .conftest import make_asset, make_concept, make_platform, make_product
from .conftest import valid_brief_values
from apps.campaigns.services import (
    create_content_brief,
    mark_content_brief_ready,
    update_content_brief,
)
from apps.knowledge.guards import _test_fixture_writes


@pytest.mark.django_db
def test_initial_campaign_and_brief_versions_must_be_one(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    with pytest.raises(ValidationError, match="version 1"):
        Campaign.objects.create(organization=own, name="Forged", version=7)
    campaign = Campaign.objects.create(organization=own, name="Valid")
    with pytest.raises(ValidationError, match="version 1"):
        ContentBrief.objects.create(
            organization=own,
            campaign=campaign,
            created_by=campaign_user,
            version=7,
        )


@pytest.mark.django_db
def test_revision_chain_cannot_be_forged_through_direct_or_bulk_writes(
    campaign_organizations, campaign_user
):
    own, other = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Own")
    other_campaign = Campaign.objects.create(organization=other, name="Other")
    source = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    foreign_source = ContentBrief.objects.create(
        organization=other, campaign=other_campaign, created_by=campaign_user
    )

    for previous, version in ((source, 2), (foreign_source, 2)):
        with pytest.raises(ValidationError, match="revision service"):
            ContentBrief.objects.create(
                organization=own,
                campaign=campaign,
                created_by=campaign_user,
                previous_version=previous,
                version=version,
            )
    with pytest.raises(ValidationError, match="revision service"):
        ContentBrief.objects.bulk_create([
            ContentBrief(
                organization=own,
                campaign=campaign,
                created_by=campaign_user,
                previous_version=source,
                version=2,
            )
        ])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model_name",
    [
        "campaign_product",
        "brief_product",
        "brief_asset",
        "brief_platform",
        "brief_concept",
    ],
)
def test_every_link_class_rejects_primary_key_mutation(
    campaign_organizations, campaign_user, model_name
):
    own, _ = campaign_organizations
    product = make_product(own)
    asset = make_asset(own, campaign_user)
    platform = make_platform()
    concept = make_concept(own, concept_type="INDUSTRY", code="LOCKED_ID")
    campaign = Campaign.objects.create(organization=own, name="Links")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    links = {
        "campaign_product": CampaignProduct.objects.create(
            organization=own, campaign=campaign, product=product
        ),
        "brief_product": ContentBriefProduct.objects.create(
            organization=own, brief=brief, product=product
        ),
        "brief_asset": ContentBriefAsset.objects.create(
            organization=own, brief=brief, asset=asset
        ),
        "brief_platform": ContentBriefPlatform.objects.create(
            organization=own, brief=brief, platform=platform
        ),
        "brief_concept": ContentBriefConceptLink.objects.create(
            organization=own,
            brief=brief,
            concept=concept,
            role="TARGET_INDUSTRY",
        ),
    }
    link = links[model_name]

    with pytest.raises(ValidationError, match="identity"):
        type(link).objects.filter(pk=link.pk).update(pk=uuid.uuid4())
    link.id = uuid.uuid4()
    with pytest.raises(ValidationError, match="identity"):
        type(link).objects.bulk_update([link], ["id"])


@pytest.mark.django_db
def test_bulk_created_link_tracks_and_protects_its_original_primary_key(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    product = make_product(own)
    campaign = Campaign.objects.create(organization=own, name="Bulk identity")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    link = ContentBriefProduct.objects.bulk_create([
        ContentBriefProduct(organization=own, brief=brief, product=product)
    ])[0]

    link.id = uuid.uuid4()
    with pytest.raises(ValidationError, match="identity"):
        link.save()


@pytest.mark.django_db
@pytest.mark.parametrize("stale_kind", ["asset", "concept"])
def test_ready_revalidates_current_asset_and_concept_state(
    campaign_organizations, campaign_user, stale_kind
):
    own, _ = campaign_organizations
    product = make_product(own)
    asset = make_asset(own, campaign_user)
    platform = make_platform()
    concept = make_concept(own, concept_type="INDUSTRY", code="READY_CURRENT")
    campaign = Campaign.objects.create(organization=own, name="Ready current")
    brief = create_content_brief(
        organization=own,
        campaign=campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[product.id],
        asset_ids=[asset.id],
        platform_ids=[platform.id],
        concept_links=[{"role": "TARGET_INDUSTRY", "concept_id": concept.id}],
    )
    if stale_kind == "asset":
        type(asset).objects.filter(pk=asset.pk).update(status="ARCHIVED")
    else:
        with _test_fixture_writes():
            type(concept).objects.filter(pk=concept.pk).update(status="DEPRECATED")

    with pytest.raises(ValidationError):
        mark_content_brief_ready(brief.id, reviewer=campaign_user)
    brief.refresh_from_db()
    assert brief.status == "DRAFT"


@pytest.mark.django_db
def test_direct_brief_relationship_creation_locks_parent_before_validation(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    product = make_product(own)
    campaign = Campaign.objects.create(organization=own, name="Lock parent")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    original = ContentBrief.objects.select_for_update

    with patch.object(
        ContentBrief.objects, "select_for_update", wraps=original
    ) as locked:
        ContentBriefProduct.objects.create(
            organization=own, brief=brief, product=product
        )

    assert locked.called


@pytest.mark.django_db
def test_draft_relationship_replacement_is_atomic_and_versions_once_without_noop_churn(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    first = make_product(own, name="First")
    second = make_product(own, name="Second")
    platform = make_platform()
    campaign = Campaign.objects.create(organization=own, name="Replace")
    brief = create_content_brief(
        organization=own,
        campaign=campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[first.id],
        asset_ids=[],
        platform_ids=[platform.id],
        concept_links=[],
    )

    changed = update_content_brief(
        brief.id,
        values={},
        product_ids=[second.id],
    )
    unchanged = update_content_brief(
        brief.id,
        values={},
        product_ids=[second.id],
    )

    assert changed.version == 2
    assert unchanged.version == 2
    assert set(unchanged.product_links.values_list("product_id", flat=True)) == {
        second.id
    }


@pytest.mark.django_db
def test_failed_draft_relationship_replacement_rolls_back_complete_set(
    campaign_organizations, campaign_user
):
    own, other = campaign_organizations
    first = make_product(own, name="First")
    foreign = make_product(other, name="Foreign")
    platform = make_platform()
    campaign = Campaign.objects.create(organization=own, name="Rollback")
    brief = create_content_brief(
        organization=own,
        campaign=campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[first.id],
        asset_ids=[],
        platform_ids=[platform.id],
        concept_links=[],
    )

    with pytest.raises(ValidationError):
        update_content_brief(brief.id, values={}, product_ids=[foreign.id])

    brief.refresh_from_db()
    assert brief.version == 1
    assert set(brief.product_links.values_list("product_id", flat=True)) == {first.id}
