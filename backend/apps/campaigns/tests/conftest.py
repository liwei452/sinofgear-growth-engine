import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import MaterialAsset
from apps.catalog.models import Product
from apps.identity.models import Organization
from apps.identity.models import Membership, Role
from apps.knowledge.models import KnowledgeConcept
from apps.knowledge.guards import _test_fixture_writes
from apps.platforms.models import Platform, PlatformCapability
from rest_framework.test import APIClient


@pytest.fixture
def campaign_organizations():
    return (
        Organization.objects.create(name="Campaign Own", slug="campaign-own"),
        Organization.objects.create(name="Campaign Other", slug="campaign-other"),
    )


@pytest.fixture
def campaign_user():
    return get_user_model().objects.create_user(username="campaign-owner")


@pytest.fixture
def campaign_roles():
    return {
        role.code: role
        for role in (
            Role.objects.create_administrator(),
            Role.objects.create_operator(),
            Role.objects.create_reviewer(),
            Role.objects.create_read_only(),
        )
    }


def create_member_client(*, organization, role, username):
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return user, client


def make_product(organization, *, name="Precision gear", status="ACTIVE"):
    return Product.objects.create(
        organization=organization,
        name_en=name,
        module_min="1.0000",
        module_max="2.0000",
        tooth_count_min=10,
        tooth_count_max=40,
        pressure_angle="20.000",
        manufacturing_capabilities=["hobbing"],
        inspection_capabilities=["CMM"],
        moq=1,
        status=status,
    )


def make_platform(*, code="LINKEDIN"):
    platform = Platform.objects.create(code=code, name=code.title())
    PlatformCapability.objects.create(platform=platform, code="PUBLISH")
    return platform


def make_concept(organization, *, concept_type, code, status="APPROVED", system=False):
    with _test_fixture_writes():
        return KnowledgeConcept.objects.create(
            scope="SYSTEM" if system else "ORGANIZATION",
            organization=None if system else organization,
            concept_type=concept_type,
            code=code,
            label_zh=code,
            label_en=code,
            status=status,
        )


def make_asset(organization, creator, *, status="ACTIVE", checksum_char="a"):
    asset = MaterialAsset(
        organization=organization,
        asset_type="IMAGE",
        original_filename="gear.png",
        mime_type="image/png",
        size_bytes=128,
        checksum=checksum_char * 64,
        language="en",
        status=status,
        tags=["gear"],
        metadata_json={},
        created_by=creator,
    )
    asset.storage_key = f"organizations/{organization.id}/assets/{asset.id}/original"
    asset.save()
    return asset


def valid_brief_values():
    return {
        "target_country": "Germany",
        "customer_type": "Industrial buyer",
        "content_objective": "Generate qualified leads",
        "cta": "Request a quote",
        "landing_page_url": "https://example.com/gears",
        "language": "en",
        "prohibited_claims": ["guaranteed zero wear"],
        "selling_points": ["Precision ground teeth"],
        "advantages": ["Short lead time"],
        "keywords": ["precision gears"],
    }
