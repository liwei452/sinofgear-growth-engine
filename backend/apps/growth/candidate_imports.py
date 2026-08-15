import csv
import hashlib
import io
import json
from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.identity.models import Organization

from .manual_imports import validate_manual_source_url
from .models import DiscoveryCandidate


ALLOWED_FIELDS = ("company_name", "country", "website", "industry")
MAX_CANDIDATE_ROWS = 200


class CandidateImportInvalid(ValueError):
    pass


def _parse_rows(import_format: str, content: str) -> list[Mapping]:
    try:
        if import_format == "CSV":
            rows = list(csv.DictReader(io.StringIO(content)))
        else:
            payload = json.loads(content)
            if not isinstance(payload, list):
                raise CandidateImportInvalid("JSON 顶层必须是客户记录数组。")
            rows = payload
    except (csv.Error, json.JSONDecodeError) as error:
        raise CandidateImportInvalid("名单内容无法解析，请检查文件格式。") from error
    if len(rows) > MAX_CANDIDATE_ROWS:
        raise CandidateImportInvalid("单次最多 200 条候选公司。")
    if not rows:
        raise CandidateImportInvalid("名单中没有可读取的客户记录。")
    return rows


def _normalize_row(row: Mapping) -> dict[str, str]:
    if not isinstance(row, Mapping):
        raise CandidateImportInvalid("每条客户记录必须是对象。")
    normalized = {
        field: str(row.get(field, "") or "").strip()
        for field in ALLOWED_FIELDS
    }
    if len(normalized["company_name"]) < 2 or len(normalized["company_name"]) > 255:
        raise CandidateImportInvalid("公司名称长度必须为 2 至 255 个字符。")
    if len(normalized["country"]) < 2 or len(normalized["country"]) > 96:
        raise CandidateImportInvalid("国家或地区长度必须为 2 至 96 个字符。")
    if len(normalized["industry"]) > 160:
        raise CandidateImportInvalid("行业名称不能超过 160 个字符。")
    if normalized["website"]:
        normalized["website"] = validate_manual_source_url(normalized["website"])
    return normalized


def import_candidate_list(
    *, organization: Organization, import_format: str, content: str,
    source_owner: str, license_contract: str, retention_days: int,
    redistribution_allowed: bool,
) -> dict:
    rows = _parse_rows(import_format, content)
    governance = {
        "source_owner": source_owner.strip(),
        "access_method": "USER_UPLOAD",
        "license_contract": license_contract.strip(),
        "robots_policy": "NOT_APPLICABLE_TO_CUSTOMER_LIST",
        "rate_limit": "NOT_APPLICABLE_TO_CUSTOMER_LIST",
        "allowed_fields": list(ALLOWED_FIELDS),
        "retention_days": retention_days,
        "redistribution_allowed": redistribution_allowed,
    }
    created_count = 0
    duplicate_count = 0
    errors = []
    with transaction.atomic():
        locked_organization = Organization.objects.select_for_update().get(pk=organization.pk)
        for row_number, row in enumerate(rows, start=1):
            try:
                normalized = _normalize_row(row)
            except (CandidateImportInvalid, ValidationError) as error:
                errors.append({"row": row_number, "message": str(error)})
                continue
            fingerprint = hashlib.sha256(
                "\n".join(normalized[field].casefold() for field in ALLOWED_FIELDS).encode("utf-8"),
            ).hexdigest()
            _candidate, created = DiscoveryCandidate.objects.get_or_create(
                organization=locked_organization,
                record_hash=fingerprint,
                defaults={
                    **normalized,
                    "import_format": import_format,
                    "source_governance": governance,
                    "raw_record": normalized,
                    "is_demo": False,
                },
            )
            if created:
                created_count += 1
            else:
                duplicate_count += 1
    return {
        "created_count": created_count,
        "duplicate_count": duplicate_count,
        "invalid_count": len(errors),
        "errors": errors,
        "queue_label": "待核实候选公司",
    }
