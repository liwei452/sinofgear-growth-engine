import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime

from .models import SourceSignal
from .services import normalize_source_url


MAX_IMPORT_ROWS = 10_000
MAX_ORIGINAL_TEXT_CHARS = 20_000
SUPPORTED_SOURCE_TYPES = frozenset({"URL", "SCREENSHOT", "CSV", "JSON", "PASTE"})


@dataclass(frozen=True)
class ImportRow:
    platform: str
    source_url: str
    signal_type: str
    original_text: str
    author_name: str = ""
    published_at: datetime | None = None
    screenshot_asset_id: UUID | None = None
    row_number: int = 1


@dataclass(frozen=True)
class ImportResult:
    rows: list[ImportRow]
    errors: list[dict[str, object]]


def _batch_error(message: str, *, code: str) -> ValidationError:
    return ValidationError({"rows": ValidationError(message, code=code)})


def _strict_text(value: str | bytes, *, label: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise _batch_error(f"{label} must be valid UTF-8.", code="INVALID_UTF8") from error
    raise _batch_error(f"{label} must be text or UTF-8 bytes.", code="INVALID_PAYLOAD")


def _row_error(row_number: int, code: str, recovery_action: str) -> dict[str, object]:
    return {"row": row_number, "code": code, "recovery_action": recovery_action}


def _parse_row(raw: object, *, row_number: int, source_type: str) -> tuple[ImportRow | None, dict | None]:
    if not isinstance(raw, dict):
        return None, _row_error(
            row_number, "ROW_OBJECT_REQUIRED", "Provide this row as a keyed record and re-import it."
        )

    source_url = raw.get("source_url")
    if not isinstance(source_url, str) or not source_url.strip():
        return None, _row_error(
            row_number,
            "SOURCE_URL_REQUIRED",
            "Provide a public source URL and re-import this row.",
        )
    try:
        normalized_url = normalize_source_url(source_url.strip())
    except ValidationError:
        return None, _row_error(
            row_number,
            "SOURCE_URL_INVALID",
            "Use a valid public HTTP or HTTPS URL and re-import this row.",
        )

    original_text = raw.get("original_text")
    if not isinstance(original_text, str) or not original_text.strip():
        return None, _row_error(
            row_number,
            "ORIGINAL_TEXT_REQUIRED",
            "Provide the public source text and re-import this row.",
        )
    if len(original_text) > MAX_ORIGINAL_TEXT_CHARS:
        return None, _row_error(
            row_number,
            "ORIGINAL_TEXT_TOO_LONG",
            f"Shorten the public source text to {MAX_ORIGINAL_TEXT_CHARS} characters and re-import this row.",
        )

    platform = raw.get("platform", "MANUAL")
    if not isinstance(platform, str) or not platform.strip() or len(platform.strip()) > 32:
        return None, _row_error(
            row_number, "PLATFORM_INVALID", "Provide a platform name of at most 32 characters."
        )
    signal_type = raw.get("signal_type", SourceSignal.SignalType.MENTION)
    if not isinstance(signal_type, str) or signal_type.strip().upper() not in SourceSignal.SignalType.values:
        return None, _row_error(
            row_number, "SIGNAL_TYPE_INVALID", "Use a supported public signal type."
        )

    author_name = raw.get("author_name", "")
    if author_name is None:
        author_name = ""
    if not isinstance(author_name, str) or len(author_name) > 255:
        return None, _row_error(
            row_number, "AUTHOR_NAME_INVALID", "Use a public author name of at most 255 characters."
        )

    published_at = raw.get("published_at")
    if published_at in (None, ""):
        parsed_published_at = None
    elif isinstance(published_at, datetime):
        parsed_published_at = published_at
    elif isinstance(published_at, str):
        parsed_published_at = parse_datetime(published_at)
        if parsed_published_at is None:
            return None, _row_error(
                row_number, "PUBLISHED_AT_INVALID", "Use an ISO 8601 publication timestamp."
            )
    else:
        return None, _row_error(
            row_number, "PUBLISHED_AT_INVALID", "Use an ISO 8601 publication timestamp."
        )

    screenshot_asset_id = raw.get("screenshot_asset_id")
    if source_type == "SCREENSHOT" and screenshot_asset_id in (None, ""):
        return None, _row_error(
            row_number,
            "SCREENSHOT_ASSET_REQUIRED",
            "Attach the screenshot asset and re-import this row.",
        )
    if screenshot_asset_id not in (None, ""):
        try:
            screenshot_asset_id = UUID(str(screenshot_asset_id))
        except (TypeError, ValueError, AttributeError):
            return None, _row_error(
                row_number,
                "SCREENSHOT_ASSET_INVALID",
                "Attach a valid screenshot asset and re-import this row.",
            )
    else:
        screenshot_asset_id = None

    return (
        ImportRow(
            platform=platform.strip().upper(),
            source_url=normalized_url,
            signal_type=signal_type.strip().upper(),
            original_text=original_text,
            author_name=author_name,
            published_at=parsed_published_at,
            screenshot_asset_id=screenshot_asset_id,
            row_number=row_number,
        ),
        None,
    )


def _result_from_rows(rows: list[tuple[int, object]], *, source_type: str) -> ImportResult:
    if len(rows) > MAX_IMPORT_ROWS:
        raise _batch_error(
            f"An import may contain at most {MAX_IMPORT_ROWS} rows.",
            code="BATCH_ROW_LIMIT_EXCEEDED",
        )
    valid: list[ImportRow] = []
    errors: list[dict[str, object]] = []
    for row_number, raw in rows:
        parsed, error = _parse_row(raw, row_number=row_number, source_type=source_type)
        if parsed is not None:
            valid.append(parsed)
        if error is not None:
            errors.append(error)
    return ImportResult(rows=valid, errors=errors)


def _mapping_payload(payload: object, *, source_type: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _batch_error(f"{source_type} payload must be an object.", code="INVALID_PAYLOAD")
    return payload


def _payload_text(payload: object, *, source_type: str) -> str:
    if isinstance(payload, dict):
        payload = payload.get("text")
    return _strict_text(payload, label=f"{source_type} payload")


def _parse_csv(payload: object) -> ImportResult:
    text = _payload_text(payload, source_type="CSV")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames:
            raise _batch_error("CSV requires a header row.", code="CSV_HEADER_REQUIRED")
        rows = [(row_number, row) for row_number, row in enumerate(reader, start=2)]
    except csv.Error as error:
        raise _batch_error("CSV is malformed.", code="CSV_INVALID") from error
    return _result_from_rows(rows, source_type="CSV")


def _parse_json(payload: object) -> ImportResult:
    if isinstance(payload, (str, bytes)):
        text = _strict_text(payload, label="JSON payload")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise _batch_error("JSON is malformed.", code="JSON_INVALID") from error
    mapping = _mapping_payload(payload, source_type="JSON")
    rows = mapping.get("rows")
    if not isinstance(rows, list):
        raise _batch_error("JSON payload requires a rows list.", code="JSON_ROWS_REQUIRED")
    return _result_from_rows(list(enumerate(rows, start=1)), source_type="JSON")


def _parse_paste(payload: object) -> ImportResult:
    text = _payload_text(payload, source_type="PASTE")
    raw_rows: list[tuple[int, object]] = []
    for row_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        source_url, separator, original_text = line.partition("\t")
        raw_rows.append(
            (
                row_number,
                {
                    "source_url": source_url,
                    "original_text": original_text if separator else "",
                },
            )
        )
    return _result_from_rows(raw_rows, source_type="PASTE")


def parse_import(payload: object, source_type: str) -> ImportResult:
    normalized_source_type = str(source_type).strip().upper()
    if normalized_source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValidationError("Unsupported source type for guided public import.")
    if normalized_source_type in {"URL", "SCREENSHOT"}:
        mapping = _mapping_payload(payload, source_type=normalized_source_type)
        return _result_from_rows([(1, mapping)], source_type=normalized_source_type)
    if normalized_source_type == "CSV":
        return _parse_csv(payload)
    if normalized_source_type == "JSON":
        return _parse_json(payload)
    return _parse_paste(payload)
