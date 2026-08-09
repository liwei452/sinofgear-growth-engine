from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.ai.models import PromptVersion
from apps.assets.models import AssetProductLink, MaterialAsset
from apps.campaigns.models import (
    Campaign,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
)
from apps.catalog.models import Product, ProductConceptLink
from apps.identity.models import Membership, Organization, Role
from apps.knowledge.models import KnowledgeConcept
from apps.platforms.models import ConnectorCredential, SocialAccount


SEED_ORGANIZATION_ID = UUID("10000000-0000-4000-8000-000000000001")
SEED_PRODUCT_ID = UUID("10000000-0000-4000-8000-000000000101")
SEED_ASSET_ID = UUID("10000000-0000-4000-8000-000000000201")
SEED_CAMPAIGN_ID = UUID("10000000-0000-4000-8000-000000000301")
SEED_BRIEF_ID = UUID("10000000-0000-4000-8000-000000000401")
SEED_PASSWORD = "PhaseA-E2E-Only!"


@pytest.mark.django_db
def test_seed_phase_a_refuses_to_run_without_explicit_e2e_setting():
    with pytest.raises(CommandError, match="E2E-only"):
        call_command("seed_phase_a")


@pytest.mark.django_db
@override_settings(PHASE_A_E2E_SEED_ALLOWED=True)
def test_seed_phase_a_is_stable_idempotent_and_repairs_owned_drift():
    call_command("seed_phase_a")

    organization = Organization.objects.get(pk=SEED_ORGANIZATION_ID)
    assert organization.slug == "phase-a-e2e-only"
    assert organization.name == "Phase A E2E Only"

    users = list(
        get_user_model().objects.filter(username__startswith="phasea_e2e_").order_by("username")
    )
    assert [user.username for user in users] == [
        "phasea_e2e_admin",
        "phasea_e2e_operator",
        "phasea_e2e_reviewer",
        "phasea_e2e_viewer",
    ]
    assert all(user.check_password(SEED_PASSWORD) for user in users)
    assert set(
        Membership.objects.filter(organization=organization).values_list("role__code", flat=True)
    ) == set(Role.Code.values)

    concepts = KnowledgeConcept.objects.filter(
        scope=KnowledgeConcept.Scope.SYSTEM,
        code__in=["HELICAL_GEAR", "DIN", "GRINDING", "PACKAGING_MACHINERY"],
    )
    assert concepts.count() == 4
    assert set(concepts.values_list("status", flat=True)) == {KnowledgeConcept.Status.APPROVED}

    product = Product.objects.get(pk=SEED_PRODUCT_ID, organization=organization)
    assert product.name_en == "Custom Helical Gear"
    assert product.status == Product.Status.ACTIVE
    assert set(
        ProductConceptLink.objects.filter(product=product, retired_at__isnull=True)
        .values_list("role", "concept__code")
    ) == {
        (ProductConceptLink.Role.TYPE, "HELICAL_GEAR"),
        (ProductConceptLink.Role.PROCESS, "GRINDING"),
        (ProductConceptLink.Role.STANDARD, "DIN"),
        (ProductConceptLink.Role.APPLICATION, "PACKAGING_MACHINERY"),
    }

    asset = MaterialAsset.objects.get(pk=SEED_ASSET_ID, organization=organization)
    assert asset.asset_type == MaterialAsset.AssetType.VIDEO
    assert asset.storage_key == f"organizations/{organization.id}/assets/{asset.id}/original"
    assert AssetProductLink.objects.filter(asset=asset, product=product).exists()

    campaign = Campaign.objects.get(pk=SEED_CAMPAIGN_ID, organization=organization)
    brief = ContentBrief.objects.get(pk=SEED_BRIEF_ID, organization=organization)
    assert campaign.status == Campaign.Status.ACTIVE
    assert brief.status == ContentBrief.Status.READY
    assert ContentBriefProduct.objects.filter(brief=brief, product=product).exists()
    assert ContentBriefAsset.objects.filter(brief=brief, asset=asset).exists()
    assert ContentBriefPlatform.objects.filter(brief=brief).count() == 5
    assert set(
        ContentBriefConceptLink.objects.filter(brief=brief).values_list("concept__code", flat=True)
    ) >= {"DIN", "PACKAGING_MACHINERY"}

    assert SocialAccount.objects.filter(organization=organization).count() == 5
    assert ConnectorCredential.objects.filter(organization=organization).count() == 5
    assert all(
        credential.secret_reference.startswith("e2e-test://")
        for credential in ConnectorCredential.objects.filter(organization=organization)
    )
    assert not ConnectorCredential.objects.filter(
        organization=organization,
        secret_reference__regex=r"(?i)(bearer|sk-|password=|access[_-]?token)",
    ).exists()
    assert PromptVersion.objects.filter(
        purpose="CONTENT_GENERATE",
        code="phase-a-e2e-content-v1",
        provider="fake",
        status=PromptVersion.Status.PUBLISHED,
    ).exists()

    first_counts = {
        "memberships": Membership.objects.filter(organization=organization).count(),
        "product_links": ProductConceptLink.objects.filter(product=product).count(),
        "assets": MaterialAsset.objects.filter(organization=organization).count(),
        "brief_products": ContentBriefProduct.objects.filter(brief=brief).count(),
        "brief_assets": ContentBriefAsset.objects.filter(brief=brief).count(),
        "brief_platforms": ContentBriefPlatform.objects.filter(brief=brief).count(),
        "brief_concepts": ContentBriefConceptLink.objects.filter(brief=brief).count(),
        "accounts": SocialAccount.objects.filter(organization=organization).count(),
    }
    first_versions = (product.version, campaign.version, brief.version)
    call_command("seed_phase_a")
    product.refresh_from_db()
    campaign.refresh_from_db()
    brief.refresh_from_db()
    assert first_counts == {
        "memberships": Membership.objects.filter(organization=organization).count(),
        "product_links": ProductConceptLink.objects.filter(product=product).count(),
        "assets": MaterialAsset.objects.filter(organization=organization).count(),
        "brief_products": ContentBriefProduct.objects.filter(brief=brief).count(),
        "brief_assets": ContentBriefAsset.objects.filter(brief=brief).count(),
        "brief_platforms": ContentBriefPlatform.objects.filter(brief=brief).count(),
        "brief_concepts": ContentBriefConceptLink.objects.filter(brief=brief).count(),
        "accounts": SocialAccount.objects.filter(organization=organization).count(),
    }
    assert (product.version, campaign.version, brief.version) == first_versions

    stable_ids = {
        "users": tuple(str(value) for value in get_user_model().objects.filter(
            username__startswith="phasea_e2e_"
        ).order_by("username").values_list("id", flat=True)),
        "memberships": tuple(str(value) for value in Membership.objects.filter(
            organization=organization
        ).order_by("user__username").values_list("id", flat=True)),
        "accounts": tuple(str(value) for value in SocialAccount.objects.filter(
            organization=organization
        ).order_by("platform__code").values_list("id", flat=True)),
    }
    organization.name = "drifted"
    organization.save(update_fields=["name", "updated_at"])
    product.name_en = "drifted"
    product.status = Product.Status.DRAFT
    product.save(update_fields=["name_en", "status", "updated_at"])
    account = SocialAccount.objects.filter(organization=organization).order_by("platform__code").first()
    account.display_name = "drifted"
    account.status = SocialAccount.Status.INACTIVE
    account.save(update_fields=["display_name", "status", "updated_at"])

    call_command("seed_phase_a")

    assert Organization.objects.get(pk=SEED_ORGANIZATION_ID).name == "Phase A E2E Only"
    product.refresh_from_db()
    assert (product.name_en, product.status) == ("Custom Helical Gear", Product.Status.ACTIVE)
    account.refresh_from_db()
    assert account.display_name != "drifted"
    assert account.status == SocialAccount.Status.ACTIVE
    assert stable_ids == {
        "users": tuple(str(value) for value in get_user_model().objects.filter(
            username__startswith="phasea_e2e_"
        ).order_by("username").values_list("id", flat=True)),
        "memberships": tuple(str(value) for value in Membership.objects.filter(
            organization=organization
        ).order_by("user__username").values_list("id", flat=True)),
        "accounts": tuple(str(value) for value in SocialAccount.objects.filter(
            organization=organization
        ).order_by("platform__code").values_list("id", flat=True)),
    }


@pytest.mark.django_db
@override_settings(PHASE_A_E2E_SEED_ALLOWED=True)
def test_seed_phase_a_never_mutates_a_non_seed_organization():
    other = Organization.objects.create(name="Customer Organization", slug="customer-org")
    before = (other.id, other.name, other.slug, other.updated_at)

    call_command("seed_phase_a")
    call_command("seed_phase_a")

    other.refresh_from_db()
    assert (other.id, other.name, other.slug, other.updated_at) == before
    assert Organization.objects.filter(pk=SEED_ORGANIZATION_ID).exists()
