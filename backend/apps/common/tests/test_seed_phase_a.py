from uuid import UUID

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import models
from django.test import override_settings

from apps.ai.models import PromptVersion
from apps.content.payloads import CONTENT_OUTPUT_SCHEMA_V2
from apps.assets.models import AssetProductLink, MaterialAsset
from apps.assets.storage import reset_object_storage
from apps.campaigns.models import (
    Campaign, CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
)
from apps.catalog.models import Product, ProductConceptLink
from apps.growth.models import (
    ChannelPackage,
    Contact,
    FieldProvenance,
    IntentSignal,
    MetricReceipt,
    TargetAccount,
)
from apps.identity.models import Membership, Organization, Role
from apps.knowledge.models import KnowledgeConcept
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


SEED_ORGANIZATION_ID = UUID("10000000-0000-4000-8000-000000000001")
SEED_PRODUCT_ID = UUID("10000000-0000-4000-8000-000000000101")
SEED_ASSET_ID = UUID("10000000-0000-4000-8000-000000000201")
SEED_CAMPAIGN_ID = UUID("10000000-0000-4000-8000-000000000301")
SEED_BRIEF_ID = UUID("10000000-0000-4000-8000-000000000401")
SEED_PASSWORD = "PhaseA-E2E-Only!"
E2E_SECRET = "unit-test-secret-with-at-least-32-bytes-of-entropy"
E2E_RUN_ID = "/canonical/temp/sinofgear-phase-a-e2e-unit"


@pytest.mark.django_db
def test_seed_phase_a_refuses_to_run_without_explicit_e2e_setting():
    with pytest.raises(CommandError, match="E2E-only"):
        call_command("seed_phase_a")


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
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
    current_content_prompt = PromptVersion.objects.get(
        purpose="CONTENT_GENERATE", version=2,
    )
    assert current_content_prompt.code == "evidence-multichannel-v2"
    assert current_content_prompt.status == PromptVersion.Status.PUBLISHED
    assert current_content_prompt.output_schema == CONTENT_OUTPUT_SCHEMA_V2
    assert PromptVersion.objects.filter(
        purpose="CONTENT_RECOMMEND",
        code="phase-a-e2e-recommend-v1",
        provider="fake",
        status=PromptVersion.Status.PUBLISHED,
    ).exists()
    assert TargetAccount.objects.filter(organization=organization, is_demo=True).count() == 3
    assert Contact.objects.filter(organization=organization).count() == 1
    assert IntentSignal.objects.filter(organization=organization, is_demo=True).count() == 3
    tiktok_package = ChannelPackage.objects.get(
        organization=organization, channel="TIKTOK", is_demo=True,
    )
    assert tiktok_package.payload["duration_seconds"] == 30
    assert tiktok_package.payload["aspect_ratio"] == "9:16"
    assert tiktok_package.status == "AWAITING_REVIEW"
    assert MetricReceipt.objects.filter(organization=organization, channel="TIKTOK").count() == 1
    assert FieldProvenance.objects.filter(organization=organization).count() >= 3

    first_counts = {
        "memberships": Membership.objects.filter(organization=organization).count(),
        "product_links": ProductConceptLink.objects.filter(product=product).count(),
        "assets": MaterialAsset.objects.filter(organization=organization).count(),
        "brief_products": ContentBriefProduct.objects.filter(brief=brief).count(),
        "brief_assets": ContentBriefAsset.objects.filter(brief=brief).count(),
        "brief_platforms": ContentBriefPlatform.objects.filter(brief=brief).count(),
        "brief_concepts": ContentBriefConceptLink.objects.filter(brief=brief).count(),
        "accounts": SocialAccount.objects.filter(organization=organization).count(),
        "growth_accounts": TargetAccount.objects.filter(organization=organization).count(),
        "growth_signals": IntentSignal.objects.filter(organization=organization).count(),
        "growth_packages": ChannelPackage.objects.filter(organization=organization).count(),
        "growth_metrics": MetricReceipt.objects.filter(organization=organization).count(),
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
        "growth_accounts": TargetAccount.objects.filter(organization=organization).count(),
        "growth_signals": IntentSignal.objects.filter(organization=organization).count(),
        "growth_packages": ChannelPackage.objects.filter(organization=organization).count(),
        "growth_metrics": MetricReceipt.objects.filter(organization=organization).count(),
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
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_never_mutates_a_non_seed_organization():
    other = Organization.objects.create(name="Customer Organization", slug="customer-org")
    before = (other.id, other.name, other.slug, other.updated_at)

    call_command("seed_phase_a")
    call_command("seed_phase_a")

    other.refresh_from_db()
    assert (other.id, other.name, other.slug, other.updated_at) == before
    assert Organization.objects.filter(pk=SEED_ORGANIZATION_ID).exists()


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_refuses_username_collision_before_any_seed_mutation():
    user_model = get_user_model()
    intruder = user_model.objects.create_user(
        username="phasea_e2e_admin",
        email="owner@example.com",
        password="keep-this-password",
    )
    original = (intruder.email, intruder.password, intruder.is_staff)

    with pytest.raises(CommandError, match="collision"):
        call_command("seed_phase_a")

    intruder.refresh_from_db()
    assert (intruder.email, intruder.password, intruder.is_staff) == original
    assert intruder.check_password("keep-this-password")
    assert not Organization.objects.filter(pk=SEED_ORGANIZATION_ID).exists()
    assert not KnowledgeConcept.objects.filter(scope=KnowledgeConcept.Scope.SYSTEM).exists()


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_refuses_fixed_and_global_identity_collisions_without_reassignment():
    other = Organization.objects.create(name="Customer", slug="customer")
    product = Product.objects.create(
        id=SEED_PRODUCT_ID,
        organization=other,
        name_zh="Customer product",
        name_en="Customer Product",
        module_min="1.0000",
        module_max="2.0000",
        tooth_count_min=12,
        tooth_count_max=24,
        pressure_angle="20.000",
        manufacturing_capabilities=["hobbing"],
        inspection_capabilities=["CMM"],
        moq=1,
    )
    platform = Platform.objects.create(code="FACEBOOK", name="Customer Facebook")
    before = (product.organization_id, product.name_en, platform.id, platform.name)

    with pytest.raises(CommandError, match="collision"):
        call_command("seed_phase_a")

    product.refresh_from_db()
    platform.refresh_from_db()
    assert (product.organization_id, product.name_en, platform.id, platform.name) == before
    assert not Organization.objects.filter(pk=SEED_ORGANIZATION_ID).exists()
    assert not KnowledgeConcept.objects.filter(scope=KnowledgeConcept.Scope.SYSTEM).exists()


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_repairs_exact_ready_brief_relationship_drift():
    call_command("seed_phase_a")
    campaign = Campaign.objects.get(pk=SEED_CAMPAIGN_ID)
    brief = ContentBrief.objects.get(pk=SEED_BRIEF_ID)
    product = Product.objects.get(pk=SEED_PRODUCT_ID)
    expected_platform_ids = set(
        Platform.objects.filter(code__in=[
            "FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE",
        ]).values_list("id", flat=True)
    )

    missing_ids = [
        (CampaignProduct, "10000000-0000-4000-8000-000000000302"),
        (ContentBriefProduct, "10000000-0000-4000-8000-000000000410"),
        (ContentBriefAsset, "10000000-0000-4000-8000-000000000411"),
        (ContentBriefPlatform, "10000000-0000-4000-8000-000000000425"),
        (ContentBriefConceptLink, "10000000-0000-4000-8000-000000000432"),
    ]
    for model, row_id in missing_ids:
        queryset = model.objects.filter(pk=UUID(row_id))
        queryset._raw_delete(queryset.db)
    call_command("seed_phase_a")

    assert set(CampaignProduct.objects.filter(campaign=campaign).values_list(
        "product_id", flat=True
    )) == {product.id}
    assert set(ContentBriefProduct.objects.filter(brief=brief).values_list(
        "product_id", flat=True
    )) == {product.id}
    assert ContentBriefAsset.objects.filter(brief=brief).count() == 1
    assert set(ContentBriefPlatform.objects.filter(brief=brief).values_list(
        "platform_id", flat=True
    )) == expected_platform_ids
    assert set(ContentBriefConceptLink.objects.filter(brief=brief).values_list(
        "role", "concept__code"
    )) == {("TARGET_INDUSTRY", "PACKAGING_MACHINERY"), ("STANDARD", "DIN")}
    brief.refresh_from_db()
    assert (brief.status, brief.version) == (ContentBrief.Status.READY, 2)


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_fails_closed_on_unexpected_ready_brief_relationship():
    call_command("seed_phase_a")
    organization = Organization.objects.get(pk=SEED_ORGANIZATION_ID)
    brief = ContentBrief.objects.get(pk=SEED_BRIEF_ID)
    unexpected = Platform.objects.create(code="E2E_UNEXPECTED", name="Unexpected")
    extra = ContentBriefPlatform(
        organization=organization, brief=brief, platform=unexpected
    )
    models.Model.save(extra, force_insert=True)

    with pytest.raises(CommandError, match="unexpected seed relationship"):
        call_command("seed_phase_a")

    assert ContentBriefPlatform.objects.filter(pk=extra.pk).exists()


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
    OBJECT_STORAGE_BACKEND="filesystem",
)
def test_seed_phase_a_rejects_mismatched_existing_object_before_asset_metadata(tmp_path):
    storage_root = tmp_path / "storage"
    key = f"organizations/{SEED_ORGANIZATION_ID}/assets/{SEED_ASSET_ID}/original"
    object_path = storage_root.joinpath(*key.split("/"))
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"malicious-existing-bytes")

    with override_settings(OBJECT_STORAGE_FILESYSTEM_ROOT=storage_root):
        reset_object_storage()
        try:
            with pytest.raises(CommandError, match="stored object collision"):
                call_command("seed_phase_a")
        finally:
            reset_object_storage()

    assert not MaterialAsset.objects.filter(pk=SEED_ASSET_ID).exists()
    assert object_path.read_bytes() == b"malicious-existing-bytes"


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_rejects_public_fixture_without_private_ownership_before_mutation():
    call_command("seed_phase_a")
    ownership_model = apps.get_model("identity", "PhaseAE2EOwnership")
    ownership_model.objects.all().delete()
    admin = get_user_model().objects.get(username="phasea_e2e_admin")
    old_password = admin.password

    with pytest.raises(CommandError, match="ownership proof"):
        call_command("seed_phase_a")

    admin.refresh_from_db()
    assert admin.password == old_password


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_rejects_bad_or_copied_signature_before_mutation():
    call_command("seed_phase_a")
    ownership_model = apps.get_model("identity", "PhaseAE2EOwnership")
    marker = ownership_model.objects.get(organization_id=SEED_ORGANIZATION_ID)
    marker.signature = "0" * 64
    marker.save(update_fields=["signature"])
    organization = Organization.objects.get(pk=SEED_ORGANIZATION_ID)
    old_name = organization.name

    with pytest.raises(CommandError, match="ownership proof"):
        call_command("seed_phase_a")

    organization.refresh_from_db()
    assert organization.name == old_name


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_rejects_marker_copied_to_a_different_run_identity():
    call_command("seed_phase_a")

    with override_settings(PHASE_A_E2E_RUN_ID=f"{E2E_RUN_ID}-other"):
        with pytest.raises(CommandError, match="ownership proof"):
            call_command("seed_phase_a")


@pytest.mark.django_db
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_A_E2E_OWNERSHIP_SECRET=E2E_SECRET,
    PHASE_A_E2E_RUN_ID=E2E_RUN_ID,
)
def test_seed_phase_a_ownership_claim_rolls_back_with_failed_first_seed(monkeypatch):
    from apps.common.management.commands.seed_phase_a import Command

    def fail_after_claim(*_args, **_kwargs):
        raise RuntimeError("stop after ownership claim")

    monkeypatch.setattr(Command, "_users", fail_after_claim)
    with pytest.raises(RuntimeError, match="stop after ownership claim"):
        call_command("seed_phase_a")

    assert not Organization.objects.filter(pk=SEED_ORGANIZATION_ID).exists()
    ownership_model = apps.get_model("identity", "PhaseAE2EOwnership")
    assert not ownership_model.objects.exists()


@pytest.mark.django_db
@override_settings(PHASE_A_E2E_SEED_ALLOWED=True)
def test_seed_phase_a_requires_private_ownership_settings():
    with pytest.raises(CommandError, match="ownership secret"):
        call_command("seed_phase_a")
