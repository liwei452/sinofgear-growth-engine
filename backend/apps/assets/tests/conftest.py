import json
import struct

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.catalog.models import Product
from apps.assets.storage import reset_object_storage
from apps.identity.models import Membership, Organization, Role


def png_bytes(marker: bytes = b"") -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + b"\x00\x00\x00\x00"

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    marker_chunk = chunk(b"tEXt", marker) if marker else b""
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + marker_chunk + chunk(b"IEND", b"")


def jpeg_bytes(marker: bytes = b"") -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xe0\x00\x04JF"
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
        + marker
        + b"\x00\xff\xd9"
    )


def webp_bytes(marker: bytes = b"") -> bytes:
    payload = b"\x00" + marker
    chunk = b"VP8 " + struct.pack("<I", len(payload)) + payload
    if len(payload) % 2:
        chunk += b"\x00"
    body = b"WEBP" + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def mp4_bytes(marker: bytes = b"") -> bytes:
    ftyp = struct.pack(">I", 20) + b"ftypisom\x00\x00\x00\x00isom"
    mdat = struct.pack(">I", 8 + len(marker)) + b"mdat" + marker
    return ftyp + mdat


def pdf_bytes(marker: bytes = b"") -> bytes:
    return (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        + marker
        + b"\nxref\n0 1\n0000000000 65535 f \n"
        b"trailer\n<< /Size 1 >>\nstartxref\n0\n%%EOF\n"
    )


PNG_BYTES = png_bytes(b"phase-a-png")


@pytest.fixture(autouse=True)
def isolated_object_storage():
    reset_object_storage()
    yield
    reset_object_storage()


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
