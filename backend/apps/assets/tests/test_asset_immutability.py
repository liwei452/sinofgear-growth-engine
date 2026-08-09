from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.assets.models import MaterialAsset
from apps.assets.services import OriginalAssetImmutable, replace_original, upload_asset
from integrations.storage.memory_storage import MemoryObjectStorage

from .test_asset_upload import ChunkOnlyUpload


@pytest.fixture
def asset(organizations) -> MaterialAsset:
    own, _ = organizations
    creator = get_user_model().objects.create_user(username="immutable")
    return upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([b"\x89PNG\r\n\x1a\nimmutable"]),
        asset_type="IMAGE",
        storage=MemoryObjectStorage(),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage_key", "organizations/other/assets/other/original"),
        ("checksum", "0" * 64),
        ("size_bytes", 999),
        ("mime_type", "image/jpeg"),
        ("asset_type", "DOCUMENT"),
        ("original_filename", "renamed.png"),
    ],
)
def test_original_identity_is_immutable_through_instance_save(asset, field, value) -> None:
    setattr(asset, field, value)

    with pytest.raises(ValidationError, match="immutable"):
        asset.save()


@pytest.mark.django_db
def test_original_identity_is_immutable_through_queryset_update(asset) -> None:
    with pytest.raises(ValidationError, match="immutable"):
        MaterialAsset.objects.filter(pk=asset.pk).update(checksum="1" * 64)


@pytest.mark.django_db
def test_original_identity_is_immutable_through_bulk_update(asset) -> None:
    asset.size_bytes += 1

    with pytest.raises(ValidationError, match="immutable"):
        MaterialAsset.objects.bulk_update([asset], ["size_bytes"])


@pytest.mark.django_db
def test_base_manager_uses_same_immutability_guard(asset) -> None:
    with pytest.raises(ValidationError, match="immutable"):
        MaterialAsset._base_manager.filter(pk=asset.pk).update(mime_type="image/webp")


@pytest.mark.django_db
def test_bulk_upsert_cannot_overwrite_existing_asset_metadata() -> None:
    with pytest.raises(ValidationError, match="upsert"):
        MaterialAsset._base_manager.bulk_create(
            [],
            update_conflicts=True,
            update_fields=["tags"],
            unique_fields=["id"],
        )


@pytest.mark.django_db
def test_replace_original_is_never_a_supported_write(asset) -> None:
    with pytest.raises(OriginalAssetImmutable):
        replace_original(asset, BytesIO(b"replacement"))


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("tags", "metadata_json"),
    [
        ("not-a-list", {}),
        (["", "valid"], {}),
        (["duplicate", "duplicate"], {}),
        ([], []),
        ([], {1: "not-a-string-key"}),
    ],
)
def test_tag_and_metadata_json_shapes_are_strictly_validated(
    organizations, tags, metadata_json
) -> None:
    own, _ = organizations
    creator = get_user_model().objects.create_user(
        username=f"invalid-json-{str(tags)[:8]}-{type(metadata_json).__name__}"
    )
    candidate = MaterialAsset(
        organization=own,
        asset_type=MaterialAsset.AssetType.IMAGE,
        original_filename="valid.png",
        mime_type="image/png",
        size_bytes=1,
        checksum="a" * 64,
        language="",
        tags=tags,
        metadata_json=metadata_json,
        created_by=creator,
    )
    candidate.storage_key = (
        f"organizations/{own.id}/assets/{candidate.id}/original"
    )

    with pytest.raises(ValidationError):
        MaterialAsset._base_manager.bulk_create([candidate])


@pytest.mark.django_db
def test_organization_checksum_uniqueness_is_database_enforced(asset) -> None:
    duplicate = MaterialAsset(
        organization=asset.organization,
        asset_type=asset.asset_type,
        original_filename="duplicate.png",
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        checksum=asset.checksum,
        language="",
        tags=[],
        metadata_json={},
        created_by=asset.created_by,
    )
    duplicate.storage_key = (
        f"organizations/{asset.organization_id}/assets/{duplicate.id}/original"
    )

    with pytest.raises(ValidationError):
        duplicate.save()
