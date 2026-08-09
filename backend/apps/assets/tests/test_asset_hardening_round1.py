from io import BytesIO
import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.assets import storage as storage_factory
from apps.assets.models import MaterialAsset, validate_metadata_json
from apps.assets.services import AssetUploadError, upload_asset
from integrations.storage.memory_storage import MemoryObjectStorage

from .conftest import jpeg_bytes, mp4_bytes, pdf_bytes, png_bytes, webp_bytes
from .test_asset_upload import ChunkOnlyUpload


def _creator(name: str):
    return get_user_model().objects.create_user(username=name)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "content_type", "asset_type"),
    [
        (b"\xff\xd8\xff", "image/jpeg", "IMAGE"),
        (b"\x89PNG\r\n\x1a\n", "image/png", "IMAGE"),
        (b"RIFF\x04\x00\x00\x00WEBP", "image/webp", "IMAGE"),
        (b"\x00\x00\x00\x0cftypisom", "video/mp4", "VIDEO"),
        (b"%PDF-1.7\n", "application/pdf", "DOCUMENT"),
    ],
)
def test_magic_only_and_truncated_supported_formats_are_rejected(
    organizations, content, content_type, asset_type
) -> None:
    own, _ = organizations
    upload = ChunkOnlyUpload([content])
    upload.content_type = content_type

    with pytest.raises(AssetUploadError, match="truncated|structure"):
        upload_asset(
            organization=own,
            creator=_creator(f"truncated-{asset_type}-{len(content)}"),
            upload=upload,
            asset_type=asset_type,
            storage=MemoryObjectStorage(),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "content_type", "asset_type"),
    [
        (jpeg_bytes(b"MZ executable"), "image/jpeg", "IMAGE"),
        (png_bytes(b"MZ harmless metadata PK\x03\x04"), "image/png", "IMAGE"),
        (webp_bytes(b"\x7fELF executable"), "image/webp", "IMAGE"),
        (mp4_bytes(b"#!/bin/sh"), "video/mp4", "VIDEO"),
        (pdf_bytes(b"MZ executable"), "application/pdf", "DOCUMENT"),
    ],
)
def test_supported_format_allows_harmless_signature_bytes_inside_valid_payload(
    organizations, content, content_type, asset_type
) -> None:
    own, _ = organizations
    upload = ChunkOnlyUpload([content])
    upload.content_type = content_type

    asset = upload_asset(
        organization=own,
        creator=_creator(f"signature-bytes-{asset_type}-{len(content)}"),
        upload=upload,
        asset_type=asset_type,
        storage=MemoryObjectStorage(),
    )

    assert asset.mime_type == content_type


@pytest.mark.django_db
def test_valid_png_with_concatenated_executable_is_rejected(organizations) -> None:
    own, _ = organizations
    content = png_bytes(b"valid metadata") + b"MZ\x90\x00executable"
    upload = ChunkOnlyUpload([content])
    upload.content_type = "image/png"

    with pytest.raises(AssetUploadError, match="truncated|structure"):
        upload_asset(
            organization=own,
            creator=_creator("concatenated-executable"),
            upload=upload,
            asset_type="IMAGE",
            storage=MemoryObjectStorage(),
        )


class CollisionStorage(MemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.delete_called = False

    def put(self, stream, key: str) -> bool:
        return False

    def delete(self, key: str) -> None:
        self.delete_called = True
        super().delete(key)


@pytest.mark.django_db
def test_upload_never_deletes_or_overwrites_a_preexisting_candidate_key(organizations) -> None:
    own, _ = organizations
    storage = CollisionStorage()

    with pytest.raises(AssetUploadError, match="already exists"):
        upload_asset(
            organization=own,
            creator=_creator("candidate-collision"),
            upload=ChunkOnlyUpload([png_bytes(b"candidate-collision")]),
            asset_type="IMAGE",
            storage=storage,
        )

    assert storage.delete_called is False
    assert MaterialAsset.objects.count() == 0


class CleanupFailureStorage(MemoryObjectStorage):
    def put(self, stream, key: str) -> bool:
        super().put(stream, key)
        return True

    def delete(self, key: str) -> None:
        raise RuntimeError("cleanup unavailable")


@pytest.mark.django_db
def test_cleanup_failure_never_masks_primary_database_exception(
    organizations, monkeypatch
) -> None:
    own, _ = organizations

    def fail_create(**kwargs):
        raise ValidationError("primary database rejection")

    monkeypatch.setattr(MaterialAsset.objects, "create", fail_create)

    with pytest.raises(ValidationError, match="primary database rejection"):
        upload_asset(
            organization=own,
            creator=_creator("cleanup-primary"),
            upload=ChunkOnlyUpload([png_bytes(b"cleanup-primary")]),
            asset_type="IMAGE",
            storage=CleanupFailureStorage(),
        )


@pytest.mark.django_db
def test_checksum_winner_is_recovered_even_when_loser_cleanup_fails(organizations) -> None:
    own, _ = organizations
    creator = _creator("cleanup-winner")
    content = png_bytes(b"cleanup-winner")
    checksum = hashlib.sha256(content).hexdigest()
    winner = None

    class WinnerRaceStorage(CleanupFailureStorage):
        def put(self, stream, key: str) -> bool:
            nonlocal winner
            created = super().put(stream, key)
            winner = MaterialAsset(
                organization=own,
                asset_type=MaterialAsset.AssetType.IMAGE,
                original_filename="winner.png",
                mime_type="image/png",
                size_bytes=len(content),
                checksum=checksum,
                language="",
                tags=["winner"],
                metadata_json={"winner": True},
                created_by=creator,
            )
            winner.storage_key = f"organizations/{own.id}/assets/{winner.id}/original"
            winner.save()
            return created

    result = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([content]),
        asset_type="IMAGE",
        storage=WinnerRaceStorage(),
    )

    assert winner is not None
    assert result.id == winner.id
    assert MaterialAsset.objects.count() == 1


@pytest.mark.django_db
def test_memory_storage_factory_reset_drops_stale_binary_state(settings) -> None:
    settings.OBJECT_STORAGE_BACKEND = "memory"
    storage_factory.reset_object_storage()
    first = storage_factory.get_object_storage()
    first.put(BytesIO(b"stale"), "stale-key")

    storage_factory.reset_object_storage()
    second = storage_factory.get_object_storage()

    assert second is not first
    with pytest.raises(FileNotFoundError):
        second.open("stale-key")


def test_metadata_json_rejects_excessive_nesting_depth() -> None:
    value: dict[str, object] = {}
    cursor = value
    for index in range(10):
        child: dict[str, object] = {}
        cursor[f"level-{index}"] = child
        cursor = child

    with pytest.raises(ValidationError, match="depth"):
        validate_metadata_json(value)


def test_metadata_json_allows_scalar_at_maximum_container_depth() -> None:
    value: dict[str, object] = {}
    cursor = value
    for index in range(7):
        child: dict[str, object] = {}
        cursor[f"level-{index}"] = child
        cursor = child
    cursor["leaf"] = "allowed"

    validate_metadata_json(value)


def test_metadata_json_rejects_oversized_utf8_serialization() -> None:
    with pytest.raises(ValidationError, match="bytes"):
        validate_metadata_json({"payload": "界" * 30_000})
