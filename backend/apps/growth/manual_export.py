from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass

from apps.content.models import PlatformContent

from .models import ChannelPackage


EXPORT_CHANNELS = {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"}
MAX_EXPORT_BYTES = 2 * 1024 * 1024
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class FourChannelExportNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class FourChannelExport:
    filename: str
    content_hash: str
    content: bytes


def _text(value: object, limit: int = 50_000) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _text_list(value: object, *, limit: int = 50, item_limit: int = 500) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, item_limit) for item in value[:limit] if isinstance(item, str)]


def _safe_filename(value: object) -> str:
    name = _text(value, 255).replace("\\", "/").split("/")[-1]
    name = "".join(character for character in name if character >= " " and character != "\x7f")
    return name or "asset"


def _content_payload(package: ChannelPackage) -> dict[str, object]:
    payload = package.payload if isinstance(package.payload, dict) else {}
    result: dict[str, object] = {
        "channel": package.channel,
        "title": _text(payload.get("title")),
        "body": _text(payload.get("body")),
        "cta": _text(payload.get("cta"), 2_000),
        "tags": _text_list(payload.get("hashtags", payload.get("tags"))),
        "utm": _text(payload.get("utm"), 2_000),
    }
    if package.channel == "TIKTOK":
        result.update({
            "duration_seconds": payload.get("duration_seconds"),
            "aspect_ratio": _text(payload.get("aspect_ratio"), 16),
            "script": _text(payload.get("script")),
            "shot_list": _text_list(payload.get("shot_list"), item_limit=2_000),
            "english_voiceover": _text(payload.get("english_voiceover")),
            "chinese_subtitles": _text(payload.get("chinese_subtitles")),
        })
    return result


def _evidence_payload(package: ChannelPackage) -> list[dict[str, object]]:
    raw_items = package.payload.get("verified_fact_evidence", [])
    if not isinstance(raw_items, list):
        return []
    result = []
    for raw in raw_items[:50]:
        if not isinstance(raw, dict):
            continue
        page = raw.get("source_page")
        result.append({
            "fact_id": _text(raw.get("fact_id"), 36),
            "field_name": _text(raw.get("field_name"), 100),
            "value": _text(raw.get("value"), 2_000),
            "source_filename": _safe_filename(raw.get("source_filename")),
            "source_page": page if isinstance(page, int) and page > 0 else None,
            "source_excerpt": _text(raw.get("source_excerpt"), 2_000),
            "is_demo": raw.get("is_demo") is True,
        })
    return result


def _asset_payload(package: ChannelPackage) -> list[dict[str, object]]:
    raw_items = package.payload.get("asset_references", [])
    if not isinstance(raw_items, list):
        return []
    result = []
    for raw in raw_items[:50]:
        if not isinstance(raw, dict):
            continue
        size = raw.get("size_bytes")
        checksum = _text(raw.get("checksum"), 64)
        result.append({
            "original_filename": _safe_filename(raw.get("original_filename")),
            "mime_type": _text(raw.get("mime_type"), 127),
            "size_bytes": size if isinstance(size, int) and 0 < size <= MAX_EXPORT_BYTES else None,
            "checksum": checksum if len(checksum) == 64 else "",
        })
    return result


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _validate_packages(*, organization, package_ids) -> list[ChannelPackage]:
    unique_ids = list(dict.fromkeys(package_ids))
    if len(unique_ids) != 4:
        raise FourChannelExportNotReady("请选择四个不同渠道的已批准内容。")
    packages = list(
        ChannelPackage.objects.select_related("source_platform_content")
        .filter(organization=organization, id__in=unique_ids)
        .order_by("channel", "id")
    )
    if len(packages) != 4 or {item.channel for item in packages} != EXPORT_CHANNELS:
        raise FourChannelExportNotReady("四渠道内容不完整，请返回推广页补齐。")
    if any(item.status != "APPROVED" for item in packages):
        raise FourChannelExportNotReady("四渠道内容必须全部经过人工批准。")
    source_ids = [item.source_platform_content_id for item in packages if item.source_platform_content_id]
    if source_ids and PlatformContent.objects.filter(previous_version_id__in=source_ids).exists():
        raise FourChannelExportNotReady("内容已有新版本，请重新审核后再下载。")
    for item in packages:
        source = item.source_platform_content
        if source is None:
            continue
        if source.organization_id != organization.id or source.status not in {
            PlatformContent.Status.APPROVED, PlatformContent.Status.PUBLISHED,
        }:
            raise FourChannelExportNotReady("内容版本已变化，请重新审核后再下载。")
        if item.payload.get("source_platform_content_id") != str(source.id):
            raise FourChannelExportNotReady("内容来源校验失败，请重新准备渠道内容。")
        if item.payload.get("source_platform_content_version") != source.version:
            raise FourChannelExportNotReady("内容版本校验失败，请重新准备渠道内容。")
    return packages


def build_four_channel_export(*, organization, package_ids) -> FourChannelExport:
    packages = _validate_packages(organization=organization, package_ids=package_ids)
    files: dict[str, bytes] = {}
    for package in packages:
        directory = package.channel.lower()
        files[f"{directory}/assets.json"] = _json_bytes(_asset_payload(package))
        files[f"{directory}/content.json"] = _json_bytes(_content_payload(package))
        files[f"{directory}/evidence.json"] = _json_bytes(_evidence_payload(package))
    manifest_base = {
        "schema_version": 1,
        "delivery": "MANUAL_ONLY",
        "data_label": "Demo / Fake" if any(item.is_demo for item in packages) else "Human-approved",
        "channels": [item.channel for item in packages],
        "files": sorted(files),
        "notice": "Local export only. No platform request was made.",
    }
    digest = hashlib.sha256()
    digest.update(_json_bytes(manifest_base))
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[path])
    content_hash = digest.hexdigest()
    files["manifest.json"] = _json_bytes({**manifest_base, "content_hash": content_hash})

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(files, key=lambda item: (item != "manifest.json", item)):
            info = zipfile.ZipInfo(path, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[path])
    content = output.getvalue()
    if len(content) > MAX_EXPORT_BYTES:
        raise FourChannelExportNotReady("发布包超过 2 MiB 限制，请精简内容后重新审核。")
    return FourChannelExport(
        filename=f"four-channel-manual-package-{content_hash[:12]}.zip",
        content_hash=content_hash,
        content=content,
    )
