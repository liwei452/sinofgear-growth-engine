import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.campaigns.models import (
    Campaign,
    CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefProduct,
)
from apps.campaigns.services import create_content_brief, mark_content_brief_ready
from apps.assets.models import AssetProductLink
from apps.catalog.models import Product

from .conftest import make_asset, make_platform, make_product, valid_brief_values


@pytest.mark.django_db
def test_campaign_and_relation_identity_are_guarded(campaign_organizations):
    own, other = campaign_organizations
    product = make_product(own)
    foreign = make_product(other, name="Foreign")
    campaign = Campaign.objects.create(organization=own, name="Launch")
    CampaignProduct.objects.create(organization=own, campaign=campaign, product=product)

    with pytest.raises(ValidationError):
        CampaignProduct.objects.create(organization=own, campaign=campaign, product=foreign)
    with pytest.raises(ValidationError):
        CampaignProduct.objects.create(organization=own, campaign=campaign, product=product)
    with pytest.raises(ValidationError):
        CampaignProduct.objects.filter(campaign=campaign).update(product=foreign)
    with pytest.raises(ProtectedError):
        CampaignProduct.objects.filter(campaign=campaign).delete()


@pytest.mark.django_db
def test_ready_requires_complete_fields_product_and_platform(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = ContentBrief.objects.create(
        organization=own,
        campaign=campaign,
        created_by=campaign_user,
    )

    with pytest.raises(ValidationError) as captured:
        mark_content_brief_ready(brief.id, reviewer=campaign_user)

    assert {
        "target_country", "selling_points", "advantages", "keywords",
        "products", "target_platforms",
    } <= set(
        captured.value.message_dict
    )


@pytest.mark.django_db
def test_list_normalization_rejects_duplicates(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Launch")
    values = valid_brief_values()
    values["selling_points"] = ["  Precision   Ground Teeth ", "precision ground teeth"]

    with pytest.raises(ValidationError) as captured:
        create_content_brief(
            organization=own,
            campaign=campaign,
            creator=campaign_user,
            values=values,
            product_ids=[],
            asset_ids=[],
            platform_ids=[],
            concept_links=[],
        )

    assert "selling_points" in captured.value.message_dict


@pytest.mark.django_db
def test_list_normalization_rejects_claim_conflicts(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Launch")
    values = valid_brief_values()
    values["selling_points"] = ["  Precision   Ground Teeth "]
    values["prohibited_claims"] = ["PRECISION GROUND TEETH"]

    with pytest.raises(ValidationError) as captured:
        create_content_brief(
            organization=own,
            campaign=campaign,
            creator=campaign_user,
            values=values,
            product_ids=[],
            asset_ids=[],
            platform_ids=[],
            concept_links=[],
        )

    assert {"selling_points", "prohibited_claims"} <= set(captured.value.message_dict)


@pytest.mark.django_db
def test_brief_asset_policy_requires_active_relevant_asset(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    selected = make_product(own)
    unrelated = make_product(own, name="Unrelated")
    asset = make_asset(own, campaign_user)
    AssetProductLink.objects.create(organization=own, asset=asset, product=unrelated)
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = ContentBrief.objects.create(
        organization=own,
        campaign=campaign,
        created_by=campaign_user,
        **valid_brief_values(),
    )
    ContentBriefProduct.objects.create(
        organization=own, brief=brief, product=selected
    )

    with pytest.raises(ValidationError, match="selected brief product"):
        ContentBriefAsset.objects.create(organization=own, brief=brief, asset=asset)


@pytest.mark.django_db
def test_archived_product_can_remain_historical_but_cannot_be_newly_selected(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    product = make_product(own)
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    link = ContentBriefProduct.objects.create(
        organization=own, brief=brief, product=product
    )
    Product.objects.filter(pk=product.pk).update(status="ARCHIVED")
    link.refresh_from_db()
    assert link.product.status == "ARCHIVED"

    other_brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    with pytest.raises(ValidationError, match="active"):
        ContentBriefProduct.objects.create(
            organization=own, brief=other_brief, product=product
        )


@pytest.mark.django_db
def test_ready_brief_rejects_generation_relevant_mutation(
    campaign_organizations, campaign_user
):
    own, _ = campaign_organizations
    product = make_product(own)
    platform = make_platform()
    campaign = Campaign.objects.create(organization=own, name="Launch")
    brief = create_content_brief(
        organization=own,
        campaign=campaign,
        creator=campaign_user,
        values=valid_brief_values(),
        product_ids=[product.id],
        asset_ids=[],
        platform_ids=[platform.id],
        concept_links=[],
    )
    ready = mark_content_brief_ready(brief.id, reviewer=campaign_user)
    ready.cta = "Silently changed"

    with pytest.raises(ValidationError, match="immutable"):
        ready.save()
    with pytest.raises(ValidationError, match="immutable"):
        ContentBrief.objects.filter(pk=ready.pk).update(cta="Bypass")
