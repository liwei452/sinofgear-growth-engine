import hashlib
import re
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
DANGEROUS_EMBEDDED_SIGNATURES = (b"MZ", b"\x7fELF", b"PK\x03\x04", b"#!/")
STRUCTURE_SCAN_BYTES = 64 * 1024


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


def _read_at(stream, offset: int, size: int) -> bytes:
    stream.seek(offset)
    return stream.read(size)


def _validate_jpeg(stream, size: int) -> None:
    if size < 20 or _read_at(stream, 0, 2) != b"\xff\xd8":
        raise AssetUploadError("JPEG is truncated or has an invalid structure.")
    offset = 2
    while offset + 4 <= size:
        marker_prefix = _read_at(stream, offset, 2)
        if marker_prefix[0] != 0xFF:
            raise AssetUploadError("JPEG is truncated or has an invalid structure.")
        marker = marker_prefix[1]
        offset += 2
        if marker == 0xD9:
            raise AssetUploadError("JPEG is truncated before image scan data.")
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            continue
        segment_length_raw = _read_at(stream, offset, 2)
        if len(segment_length_raw) != 2:
            break
        segment_length = int.from_bytes(segment_length_raw, "big")
        if segment_length < 2 or offset + segment_length > size:
            break
        if marker == 0xDA:
            scan_start = offset + segment_length
            if scan_start >= size - 2 or _read_at(stream, size - 2, 2) != b"\xff\xd9":
                break
            return
        offset += segment_length
    raise AssetUploadError("JPEG is truncated or has an invalid structure.")


def _validate_png(stream, size: int) -> None:
    if size < 45 or _read_at(stream, 0, 8) != b"\x89PNG\r\n\x1a\n":
        raise AssetUploadError("PNG is truncated or has an invalid structure.")
    offset = 8
    first = True
    while offset + 12 <= size:
        chunk_header = _read_at(stream, offset, 8)
        length = int.from_bytes(chunk_header[:4], "big")
        kind = chunk_header[4:]
        chunk_end = offset + 12 + length
        if chunk_end > size:
            break
        if first and (kind != b"IHDR" or length != 13):
            break
        if kind == b"IEND":
            if length == 0 and chunk_end == size:
                return
            break
        first = False
        offset = chunk_end
    raise AssetUploadError("PNG is truncated or has an invalid structure.")


def _validate_webp(stream, size: int) -> None:
    header = _read_at(stream, 0, 12)
    if (
        size < 22
        or len(header) != 12
        or header[:4] != b"RIFF"
        or header[8:] != b"WEBP"
        or int.from_bytes(header[4:8], "little") + 8 != size
    ):
        raise AssetUploadError("WebP is truncated or has an invalid structure.")
    offset = 12
    recognized = False
    while offset + 8 <= size:
        chunk_header = _read_at(stream, offset, 8)
        kind = chunk_header[:4]
        length = int.from_bytes(chunk_header[4:], "little")
        chunk_end = offset + 8 + length + (length % 2)
        if chunk_end > size:
            break
        recognized = recognized or kind in {b"VP8 ", b"VP8L", b"VP8X"}
        offset = chunk_end
    if not recognized or offset != size:
        raise AssetUploadError("WebP is truncated or has an invalid structure.")


def _validate_mp4(stream, size: int) -> None:
    if size < 28:
        raise AssetUploadError("MP4 is truncated or has an invalid structure.")
    offset = 0
    first = True
    has_media_box = False
    while offset + 8 <= size:
        header = _read_at(stream, offset, 8)
        box_size = int.from_bytes(header[:4], "big")
        kind = header[4:]
        header_size = 8
        if box_size == 1:
            extended = _read_at(stream, offset + 8, 8)
            if len(extended) != 8:
                break
            box_size = int.from_bytes(extended, "big")
            header_size = 16
        elif box_size == 0:
            box_size = size - offset
        if box_size < header_size or offset + box_size > size:
            break
        if first and (kind != b"ftyp" or box_size < 16):
            break
        has_media_box = has_media_box or kind in {b"moov", b"mdat"}
        first = False
        offset += box_size
    if first or not has_media_box or offset != size:
        raise AssetUploadError("MP4 is truncated or has an invalid structure.")


def _validate_pdf(stream, size: int) -> None:
    header = _read_at(stream, 0, min(size, 1024))
    tail = _read_at(stream, max(0, size - STRUCTURE_SCAN_BYTES), min(size, STRUCTURE_SCAN_BYTES))
    if (
        not re.match(rb"%PDF-1\.[0-7](?:\r?\n|\r)", header)
        or b"xref" not in tail
        or b"trailer" not in tail
        or b"startxref" not in tail
        or not tail.rstrip().endswith(b"%%EOF")
    ):
        raise AssetUploadError("PDF is truncated or has an invalid structure.")


def _validate_no_polyglot_signatures(stream, size: int) -> None:
    head = _read_at(stream, 0, min(size, STRUCTURE_SCAN_BYTES))
    tail_offset = max(0, size - STRUCTURE_SCAN_BYTES)
    tail = b"" if tail_offset == 0 else _read_at(stream, tail_offset, STRUCTURE_SCAN_BYTES)
    inspected = head + tail
    if any(signature in inspected for signature in DANGEROUS_EMBEDDED_SIGNATURES):
        raise AssetUploadError("Upload contains an unsafe polyglot-like payload signature.")


def _validate_structure(stream, *, size: int, mime_type: str) -> None:
    validators = {
        "image/jpeg": _validate_jpeg,
        "image/png": _validate_png,
        "image/webp": _validate_webp,
        "video/mp4": _validate_mp4,
        "application/pdf": _validate_pdf,
    }
    validators[mime_type](stream, size)
    _validate_no_polyglot_signatures(stream, size)
    stream.seek(0)


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
        _validate_structure(spool, size=size, mime_type=detected_mime)
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
        object_created = object_storage.put(spool, candidate.storage_key)
        if not object_created:
            winner = MaterialAsset.objects.filter(
                organization=organization,
                checksum=checksum,
            ).first()
            if winner is not None:
                return _mark_upload_result(winner, created=False)
            raise AssetUploadError("Original storage key already exists; upload was not overwritten.")
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
            winner = MaterialAsset.objects.filter(
                organization=organization,
                checksum=checksum,
            ).first()
            try:
                object_storage.delete(candidate.storage_key)
            except Exception:
                pass
            if winner is not None:
                return _mark_upload_result(winner, created=False)
            raise
        except Exception:
            try:
                object_storage.delete(candidate.storage_key)
            except Exception:
                pass
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
