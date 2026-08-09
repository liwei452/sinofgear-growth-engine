import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.identity.models import Membership, Organization, Role


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"phase-a-png"


@pytest.fixture
def organizations() -> tuple[Organization, Organization]:
    return (
        Organization.objects.create(name="Asset Own", slug="asset-own"),
        Organization.objects.create(name="Asset Other", slug="asset-other"),
    )


@pytest.fixture
def roles() -> dict[str, Role]:
    return {
        role.code: role
        for role in (
            Role.objects.create_administrator(),
            Role.objects.create_operator(),
            Role.objects.create_reviewer(),
            Role.objects.create_read_only(),
        )
    }


def create_member_client(
    *, organization: Organization, role: Role, username: str
) -> tuple[Membership, APIClient]:
    user = get_user_model().objects.create_user(username=username, password="asset-test-pass")
    membership = Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="asset-test-pass")
    return membership, client


def make_product(organization: Organization, *, name: str, status: str = "ACTIVE") -> Product:
    return Product.objects.create(
        organization=organization,
        name_zh="",
        name_en=name,
        module_min="1.0000",
        module_max="2.0000",
        tooth_count_min=8,
        tooth_count_max=80,
        pressure_angle="20.000",
        accuracy_grade="ISO 8",
        heat_treatment="",
        surface_treatment="",
        manufacturing_capabilities=["hobbing"],
        inspection_capabilities=["CMM"],
        moq=1,
        lead_time="",
        landing_page_url="",
        status=status,
        internal_notes="",
    )


def upload_payload(
    *,
    content: bytes = PNG_BYTES,
    filename: str = "gear-profile.png",
    content_type: str = "image/png",
    asset_type: str = "IMAGE",
    tags: list[str] | None = None,
    metadata_json: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "file": SimpleUploadedFile(filename, content, content_type=content_type),
        "asset_type": asset_type,
        "language": "en",
        "tags": json.dumps(tags if tags is not None else ["gear"]),
        "metadata_json": json.dumps(metadata_json if metadata_json is not None else {"source": "test"}),
    }
