import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.assets.models import MaterialAsset
from apps.assets.services import AssetUploadError, upload_asset
from integrations.storage.memory_storage import MemoryObjectStorage

from .conftest import jpeg_bytes, mp4_bytes, pdf_bytes, png_bytes, webp_bytes


class TrackingMemoryStorage(MemoryObjectStorage):
    def __init__(self, *, on_put=None) -> None:
        super().__init__()
        self.put_keys: list[str] = []
        self.deleted_keys: list[str] = []
        self.on_put = on_put

    def put(self, stream, key: str) -> bool:
        created = super().put(stream, key)
        self.put_keys.append(key)
        if created and self.on_put is not None:
            self.on_put(key)
        return created

    def delete(self, key: str) -> None:
        self.deleted_keys.append(key)
        super().delete(key)


class ChunkOnlyUpload:
    name = "chunked.png"
    content_type = "image/png"

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.chunk_calls = 0

    def chunks(self, chunk_size=None):
        self.chunk_calls += 1
        yield from self._chunks

    def read(self, *args, **kwargs):
        raise AssertionError("upload service must consume chunks")


def _creator(username: str):
    return get_user_model().objects.create_user(username=username)


@pytest.mark.django_db
def test_same_org_duplicate_reuses_asset_without_overwriting_metadata(organizations) -> None:
    own, _ = organizations
    creator = _creator("same-org")
    storage = TrackingMemoryStorage()
    content = png_bytes(b"identical")

    first = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([content[:8], content[8:]]),
        asset_type="IMAGE",
        tags=["first"],
        metadata_json={"caption": "original"},
        storage=storage,
    )
    second = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([content]),
        asset_type="IMAGE",
        tags=["second"],
        metadata_json={"caption": "replacement"},
        storage=storage,
    )

    assert first.id == second.id
    assert MaterialAsset.objects.count() == 1
    assert storage.put_keys == [first.storage_key]
    first.refresh_from_db()
    assert first.tags == ["first"]
    assert first.metadata_json == {"caption": "original"}


@pytest.mark.django_db
def test_identical_bytes_in_different_orgs_have_different_assets_and_keys(organizations) -> None:
    own, other = organizations
    creator = _creator("cross-org")
    storage = TrackingMemoryStorage()
    content = png_bytes(b"cross-org")

    first = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([content]),
        asset_type="IMAGE",
        storage=storage,
    )
    second = upload_asset(
        organization=other,
        creator=creator,
        upload=ChunkOnlyUpload([content]),
        asset_type="IMAGE",
        storage=storage,
    )

    assert first.id != second.id
    assert first.storage_key != second.storage_key
    assert first.storage_key == f"organizations/{own.id}/assets/{first.id}/original"
    assert second.storage_key == f"organizations/{other.id}/assets/{second.id}/original"


@pytest.mark.django_db
def test_upload_streams_chunks_and_never_leaks_filename_into_key(organizations) -> None:
    own, _ = organizations
    creator = _creator("chunked")
    content = png_bytes(b"more-bytes")
    upload = ChunkOnlyUpload([content[:8], content[8:24], content[24:]])

    asset = upload_asset(
        organization=own,
        creator=creator,
        upload=upload,
        asset_type="IMAGE",
        storage=TrackingMemoryStorage(),
    )

    assert upload.chunk_calls == 1
    assert asset.storage_key == f"organizations/{own.id}/assets/{asset.id}/original"
    assert "chunked" not in asset.storage_key
    assert "png" not in asset.storage_key


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "client_mime", "asset_type", "verified_mime"),
    [
        (jpeg_bytes(b"jpeg"), "image/jpeg", "IMAGE", "image/jpeg"),
        (png_bytes(b"png"), "image/png", "IMAGE", "image/png"),
        (webp_bytes(b"webp"), "image/webp", "IMAGE", "image/webp"),
        (mp4_bytes(b"mp4"), "video/mp4", "VIDEO", "video/mp4"),
        (pdf_bytes(b"pdf"), "application/pdf", "DOCUMENT", "application/pdf"),
    ],
)
def test_server_signature_detection_accepts_phase_a_formats(
    organizations, content, client_mime, asset_type, verified_mime
) -> None:
    own, _ = organizations
    creator = _creator(f"signature-{asset_type}-{verified_mime}")
    upload = ChunkOnlyUpload([content])
    upload.content_type = client_mime

    asset = upload_asset(
        organization=own,
        creator=creator,
        upload=upload,
        asset_type=asset_type,
        storage=TrackingMemoryStorage(),
    )

    assert asset.mime_type == verified_mime
    assert asset.size_bytes == len(content)
    assert asset.checksum == hashlib.sha256(content).hexdigest()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "content_type", "asset_type", "message"),
    [
        (b"", "image/png", "IMAGE", "empty"),
        (b"MZ\x90\x00executable", "application/octet-stream", "DOCUMENT", "unsupported"),
        (b"#!/bin/sh\necho unsafe", "text/plain", "DOCUMENT", "unsupported"),
        (png_bytes(b"real"), "image/jpeg", "IMAGE", "MIME"),
        (pdf_bytes(b"real"), "application/pdf", "IMAGE", "asset type"),
    ],
)
def test_invalid_upload_content_is_rejected(
    organizations, content, content_type, asset_type, message
) -> None:
    own, _ = organizations
    creator = _creator(f"reject-{len(content)}-{asset_type}")
    upload = ChunkOnlyUpload([content])
    upload.content_type = content_type

    with pytest.raises(AssetUploadError, match=message):
        upload_asset(
            organization=own,
            creator=creator,
            upload=upload,
            asset_type=asset_type,
            storage=TrackingMemoryStorage(),
        )

    assert MaterialAsset.objects.count() == 0


@pytest.mark.django_db
def test_oversized_upload_stops_without_writing_object(organizations) -> None:
    own, _ = organizations
    creator = _creator("oversized")
    storage = TrackingMemoryStorage()

    with pytest.raises(AssetUploadError, match="maximum"):
        upload_asset(
            organization=own,
            creator=creator,
            upload=ChunkOnlyUpload([png_bytes(b"too-large")]),
            asset_type="IMAGE",
            storage=storage,
            max_size_bytes=12,
        )

    assert storage.put_keys == []
    assert MaterialAsset.objects.count() == 0


@pytest.mark.django_db
def test_database_failure_deletes_only_the_newly_written_object(
    organizations, monkeypatch
) -> None:
    own, _ = organizations
    creator = _creator("db-failure")
    storage = TrackingMemoryStorage()

    def fail_create(**kwargs):
        raise ValidationError("simulated database rejection")

    monkeypatch.setattr(MaterialAsset.objects, "create", fail_create)

    with pytest.raises(ValidationError, match="simulated"):
        upload_asset(
            organization=own,
            creator=creator,
            upload=ChunkOnlyUpload([png_bytes(b"db-failure")]),
            asset_type="IMAGE",
            storage=storage,
        )

    assert storage.deleted_keys == storage.put_keys
    assert len(storage.deleted_keys) == 1


@pytest.mark.django_db
def test_checksum_race_returns_winner_and_compensates_losing_object(organizations) -> None:
    own, _ = organizations
    creator = _creator("race")
    content = png_bytes(b"race")
    checksum = hashlib.sha256(content).hexdigest()
    winner = None

    def create_winner(_losing_key: str) -> None:
        nonlocal winner
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
        winner.storage_key = (
            f"organizations/{own.id}/assets/{winner.id}/original"
        )
        winner.save()

    storage = TrackingMemoryStorage(on_put=create_winner)

    result = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([content]),
        asset_type="IMAGE",
        storage=storage,
    )

    assert winner is not None
    assert result.id == winner.id
    assert MaterialAsset.objects.count() == 1
    assert storage.deleted_keys == storage.put_keys
    assert winner.storage_key not in storage.deleted_keys
