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
PREPARED_IMPORT_SCHEMA = "GUIDED_IMPORT_V1"
PREPARED_ROW_FIELDS = frozenset(
    {
        "platform",
        "source_url",
        "signal_type",
        "original_text",
        "author_name",
        "published_at",
        "screenshot_asset_id",
        "row_number",
    }
)
CSV_IMPORT_COLUMNS = PREPARED_ROW_FIELDS - {"row_number"}
PREPARED_ERROR_FIELDS = frozenset({"row", "code", "recovery_action"})
SAFE_RECOVERY_ACTIONS = {
    "ROW_OBJECT_REQUIRED": "Provide this row as a keyed record and re-import it.",
    "SOURCE_URL_REQUIRED": "Provide a public source URL and re-import this row.",
    "SOURCE_URL_INVALID": "Use a valid public HTTP or HTTPS URL and re-import this row.",
    "ORIGINAL_TEXT_REQUIRED": "Provide the public source text and re-import this row.",
    "ORIGINAL_TEXT_TOO_LONG": (
        f"Shorten the public source text to {MAX_ORIGINAL_TEXT_CHARS} characters and re-import this row."
    ),
    "PLATFORM_INVALID": "Provide a platform name of at most 32 characters.",
    "SIGNAL_TYPE_INVALID": "Use a supported public signal type.",
    "AUTHOR_NAME_INVALID": "Use a public author name of at most 255 characters.",
    "PUBLISHED_AT_INVALID": "Use an ISO 8601 publication timestamp.",
    "SCREENSHOT_ASSET_REQUIRED": "Attach the screenshot asset and re-import this row.",
    "SCREENSHOT_ASSET_INVALID": "Attach a valid screenshot asset and re-import this row.",
    "CSV_COLUMNS_UNEXPECTED": "Use only supported CSV columns and re-import the file.",
    "CSV_SURPLUS_VALUES": (
        "Remove values without matching CSV headers and re-import this row."
    ),
    "BATCH_ROW_LIMIT_EXCEEDED": "Reduce the import to 10,000 rows or fewer and retry.",
    "INVALID_UTF8": "Encode the import as UTF-8 and retry.",
    "INVALID_PAYLOAD": "Provide a supported guided import payload and retry.",
    "CSV_HEADER_REQUIRED": "Add the supported CSV header row and retry.",
    "CSV_INVALID": "Correct the malformed CSV and retry.",
    "JSON_INVALID": "Correct the malformed JSON and retry.",
    "JSON_ROWS_REQUIRED": "Provide a JSON object with a rows list and retry.",
    "IMPORT_PAYLOAD_INVALID": "Correct the guided import payload and retry.",
}


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


def _strict_csv_text(value: str | bytes) -> str:
    if isinstance(value, str):
        return value[1:] if value.startswith("\ufeff") else value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise _batch_error("CSV payload must be valid UTF-8.", code="INVALID_UTF8") from error
    raise _batch_error("CSV payload must be text or UTF-8 bytes.", code="INVALID_PAYLOAD")


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


def _csv_payload_text(payload: object) -> str:
    if isinstance(payload, dict):
        payload = payload.get("text")
    return _strict_csv_text(payload)


def _parse_csv(payload: object) -> ImportResult:
    text = _csv_payload_text(payload)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if not reader.fieldnames:
            raise _batch_error("CSV requires a header row.", code="CSV_HEADER_REQUIRED")
        fieldnames = list(reader.fieldnames)
        if len(fieldnames) != len(set(fieldnames)) or not set(fieldnames) <= CSV_IMPORT_COLUMNS:
            return ImportResult(
                rows=[],
                errors=[
                    _row_error(
                        1,
                        "CSV_COLUMNS_UNEXPECTED",
                        "Use only supported CSV columns and re-import the file.",
                    )
                ],
            )
        parsed_rows = list(enumerate(reader, start=2))
    except csv.Error as error:
        raise _batch_error("CSV is malformed.", code="CSV_INVALID") from error
    if len(parsed_rows) > MAX_IMPORT_ROWS:
        raise _batch_error(
            f"An import may contain at most {MAX_IMPORT_ROWS} rows.",
            code="BATCH_ROW_LIMIT_EXCEEDED",
        )
    rows: list[tuple[int, object]] = []
    errors: list[dict[str, object]] = []
    for row_number, row in parsed_rows:
        if None in row:
            errors.append(
                _row_error(
                    row_number,
                    "CSV_SURPLUS_VALUES",
                    "Remove values without matching CSV headers and re-import this row.",
                )
            )
            continue
        rows.append((row_number, row))
    result = _result_from_rows(rows, source_type="CSV")
    return ImportResult(rows=result.rows, errors=[*errors, *result.errors])


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


def _serialized_row(row: ImportRow) -> dict[str, object]:
    return {
        "platform": row.platform,
        "source_url": row.source_url,
        "signal_type": row.signal_type,
        "original_text": row.original_text,
        "author_name": row.author_name,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "screenshot_asset_id": str(row.screenshot_asset_id) if row.screenshot_asset_id else None,
        "row_number": row.row_number,
    }


def _serialized_batch_error(error: ValidationError) -> dict[str, object]:
    details = error.error_dict.get("rows", []) if hasattr(error, "error_dict") else []
    detail = details[0] if details else None
    code = getattr(detail, "code", None) or "IMPORT_PAYLOAD_INVALID"
    return {
        "row": None,
        "code": code,
        "recovery_action": SAFE_RECOVERY_ACTIONS.get(
            code, SAFE_RECOVERY_ACTIONS["IMPORT_PAYLOAD_INVALID"]
        ),
    }


def prepare_import_reference(payload: object, source_type: str) -> dict[str, object]:
    """Parse untrusted input and return the only guided-import shape safe to persist."""
    normalized_source_type = str(source_type).strip().upper()
    if normalized_source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValidationError("Unsupported source type for guided public import.")
    import_asset_id = payload.get("import_asset_id") if isinstance(payload, dict) else None
    try:
        result = parse_import(payload, source_type=normalized_source_type)
    except ValidationError as error:
        result = ImportResult(rows=[], errors=[_serialized_batch_error(error)])
    reference: dict[str, object] = {
        "schema": PREPARED_IMPORT_SCHEMA,
        "rows": [_serialized_row(row) for row in result.rows],
        "errors": [dict(error) for error in result.errors],
    }
    if import_asset_id not in (None, ""):
        reference["import_asset_id"] = str(import_asset_id)
    validate_prepared_import_reference(reference, source_type=normalized_source_type)
    return reference


def validate_prepared_import_reference(reference: object, *, source_type: str) -> None:
    if not isinstance(reference, dict):
        raise ValidationError(
            {"input_reference": "Guided imports require a prepared input reference."}
        )
    allowed_top_level = {"schema", "rows", "errors", "import_asset_id"}
    if (
        set(reference) - allowed_top_level
        or reference.get("schema") != PREPARED_IMPORT_SCHEMA
        or not isinstance(reference.get("rows"), list)
        or not isinstance(reference.get("errors"), list)
    ):
        raise ValidationError(
            {"input_reference": "Guided imports require a prepared input reference."}
        )
    if len(reference["rows"]) > MAX_IMPORT_ROWS:
        raise ValidationError(
            {"input_reference": "Guided imports require prepared rows within the supported limit."}
        )
    for row in reference["rows"]:
        if not isinstance(row, dict) or set(row) != PREPARED_ROW_FIELDS:
            raise ValidationError(
                {"input_reference": "Guided imports require prepared rows with supported fields."}
            )
        row_number = row.get("row_number")
        if (
            not isinstance(row_number, int)
            or isinstance(row_number, bool)
            or row_number < 1
            or not (row.get("published_at") is None or isinstance(row.get("published_at"), str))
            or not (
                row.get("screenshot_asset_id") is None
                or isinstance(row.get("screenshot_asset_id"), str)
            )
        ):
            raise ValidationError(
                {"input_reference": "Guided imports require prepared rows with valid field types."}
            )
        parsed, parse_error = _parse_row(
            row,
            row_number=row_number,
            source_type=str(source_type).strip().upper(),
        )
        if parsed is None or parse_error is not None:
            raise ValidationError(
                {"input_reference": "Guided imports require prepared rows with valid values."}
            )
    for error in reference["errors"]:
        if (
            not isinstance(error, dict)
            or set(error) != PREPARED_ERROR_FIELDS
            or not isinstance(error.get("code"), str)
            or not isinstance(error.get("recovery_action"), str)
            or not (
                error.get("row") is None
                or (
                    isinstance(error.get("row"), int)
                    and not isinstance(error.get("row"), bool)
                    and error.get("row") >= 1
                )
            )
            or SAFE_RECOVERY_ACTIONS.get(error.get("code"))
            != error.get("recovery_action")
        ):
            raise ValidationError(
                {"input_reference": "Guided imports require prepared errors with controlled fields."}
            )
    if "import_asset_id" in reference:
        try:
            UUID(str(reference["import_asset_id"]))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValidationError(
                {"input_reference": "Guided imports require a prepared valid asset reference."}
            ) from error


def import_result_from_reference(reference: object, source_type: str) -> ImportResult:
    validate_prepared_import_reference(reference, source_type=source_type)
    rows: list[ImportRow] = []
    for raw in reference["rows"]:
        row, error = _parse_row(
            raw,
            row_number=raw["row_number"],
            source_type=str(source_type).strip().upper(),
        )
        if error is not None or row is None:
            raise ValidationError(
                {"input_reference": "Prepared import row no longer satisfies its contract."}
            )
        rows.append(row)
    return ImportResult(rows=rows, errors=[dict(error) for error in reference["errors"]])
