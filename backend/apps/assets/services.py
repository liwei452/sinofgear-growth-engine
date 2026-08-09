import hashlib
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Product

from .models import (
    AssetProductLink,
    MaterialAsset,
    validate_metadata_json,
    validate_tags,
)
from .storage import get_object_storage


class AssetUploadError(ValueError):
    pass


class OriginalAssetImmutable(ValidationError):
    pass


MIME_ASSET_TYPES = {
    "image/jpeg": MaterialAsset.AssetType.IMAGE,
    "image/png": MaterialAsset.AssetType.IMAGE,
    "image/webp": MaterialAsset.AssetType.IMAGE,
    "video/mp4": MaterialAsset.AssetType.VIDEO,
    "application/pdf": MaterialAsset.AssetType.DOCUMENT,
}
MIME_ALIASES = {"image/jpg": "image/jpeg"}


def _detect_mime(header: bytes) -> str | None:
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _iter_upload_chunks(upload):
    chunks = getattr(upload, "chunks", None)
    if callable(chunks):
        yield from chunks(chunk_size=64 * 1024)
        return
    while True:
        chunk = upload.read(64 * 1024)
        if not chunk:
            return
        yield chunk


def _stage_upload(upload, *, max_size_bytes: int):
    spool = tempfile.SpooledTemporaryFile(
        max_size=settings.ASSET_SPOOL_MEMORY_BYTES,
        mode="w+b",
    )
    digest = hashlib.sha256()
    header = bytearray()
    size = 0
    try:
        for chunk in _iter_upload_chunks(upload):
            if not isinstance(chunk, bytes):
                chunk = bytes(chunk)
            if not chunk:
                continue
            size += len(chunk)
            if size > max_size_bytes:
                raise AssetUploadError(
                    f"Upload exceeds the maximum size of {max_size_bytes} bytes."
                )
            digest.update(chunk)
            spool.write(chunk)
            if len(header) < 4096:
                header.extend(chunk[: 4096 - len(header)])
        if size == 0:
            raise AssetUploadError("Upload must not be empty.")
        detected_mime = _detect_mime(bytes(header))
        if detected_mime is None:
            raise AssetUploadError("Upload has an unsupported or unsafe file signature.")
        spool.seek(0)
        return spool, size, digest.hexdigest(), detected_mime
    except Exception:
        spool.close()
        raise


def _validate_upload_contract(*, upload, asset_type: str, detected_mime: str) -> None:
    if asset_type not in MaterialAsset.AssetType.values:
        raise AssetUploadError("Unknown asset type.")
    expected_type = MIME_ASSET_TYPES[detected_mime]
    if asset_type != expected_type:
        raise AssetUploadError(
            f"Detected MIME does not match the requested asset type {asset_type}."
        )
    client_mime = getattr(upload, "content_type", "") or ""
    normalized_client_mime = MIME_ALIASES.get(client_mime.lower(), client_mime.lower())
    if normalized_client_mime and normalized_client_mime != detected_mime:
        raise AssetUploadError(
            f"Client MIME {client_mime} does not match verified MIME {detected_mime}."
        )


def _mark_upload_result(asset: MaterialAsset, *, created: bool) -> MaterialAsset:
    asset._upload_created = created
    return asset


def upload_asset(
    *,
    organization,
    creator,
    upload,
    asset_type: str,
    language: str = "",
    tags=None,
    metadata_json=None,
    storage=None,
    max_size_bytes: int | None = None,
) -> MaterialAsset:
    tags = [] if tags is None else tags
    metadata_json = {} if metadata_json is None else metadata_json
    validate_tags(tags)
    validate_metadata_json(metadata_json)
    max_size_bytes = max_size_bytes or settings.ASSET_MAX_UPLOAD_BYTES
    spool, size, checksum, detected_mime = _stage_upload(
        upload,
        max_size_bytes=max_size_bytes,
    )
    try:
        _validate_upload_contract(
            upload=upload,
            asset_type=asset_type,
            detected_mime=detected_mime,
        )
        existing = MaterialAsset.objects.filter(
            organization=organization,
            checksum=checksum,
        ).first()
        if existing is not None:
            return _mark_upload_result(existing, created=False)

        candidate = MaterialAsset(
            organization=organization,
            asset_type=asset_type,
            original_filename=Path(getattr(upload, "name", "upload")).name[:255],
            mime_type=detected_mime,
            size_bytes=size,
            checksum=checksum,
            language=language,
            tags=tags,
            metadata_json=metadata_json,
            created_by=creator,
        )
        candidate.storage_key = (
            f"organizations/{organization.id}/assets/{candidate.id}/original"
        )
        object_storage = storage or get_object_storage()
        object_storage.put(spool, candidate.storage_key)
        try:
            with transaction.atomic():
                created_asset = MaterialAsset.objects.create(
                    id=candidate.id,
                    organization=candidate.organization,
                    asset_type=candidate.asset_type,
                    storage_key=candidate.storage_key,
                    original_filename=candidate.original_filename,
                    mime_type=candidate.mime_type,
                    size_bytes=candidate.size_bytes,
                    checksum=candidate.checksum,
                    language=candidate.language,
                    tags=candidate.tags,
                    metadata_json=candidate.metadata_json,
                    created_by=candidate.created_by,
                )
        except (IntegrityError, ValidationError):
            object_storage.delete(candidate.storage_key)
            winner = MaterialAsset.objects.filter(
                organization=organization,
                checksum=checksum,
            ).first()
            if winner is not None:
                return _mark_upload_result(winner, created=False)
            raise
        except Exception:
            object_storage.delete(candidate.storage_key)
            raise
        return _mark_upload_result(created_asset, created=True)
    finally:
        spool.close()


def replace_original(asset: MaterialAsset, stream) -> None:
    raise OriginalAssetImmutable("Original asset binary identity is immutable.")


@transaction.atomic
def link_asset_to_product(*, asset: MaterialAsset, product: Product):
    locked_asset = MaterialAsset.objects.select_for_update().get(pk=asset.pk)
    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    existing = AssetProductLink.objects.filter(
        asset=locked_asset,
        product=locked_product,
    ).first()
    if existing is not None:
        return existing, False
    try:
        return (
            AssetProductLink.objects.create(
                organization=locked_asset.organization,
                asset=locked_asset,
                product=locked_product,
            ),
            True,
        )
    except IntegrityError:
        return AssetProductLink.objects.get(asset=locked_asset, product=locked_product), False
