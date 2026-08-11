from __future__ import annotations

import re
import unicodedata

from jsonschema.validators import validator_for


UUID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"

FROZEN_SOURCE_EVIDENCE_FIELDS = frozenset(
    {
        "schema",
        "id",
        "organization_id",
        "source_signal_id",
        "source_content_id",
        "monitoring_target_id",
        "monitoring_target_type",
        "monitoring_target_collection_mode",
        "monitoring_target_platform",
        "monitoring_target_external_reference",
        "monitoring_target_normalized_url",
        "evidence_type",
        "original_text",
        "translated_text",
        "translated_language",
        "source_url",
        "platform",
        "public_published_at",
        "captured_at",
        "collection_method",
        "language",
        "screenshot_asset_id",
        "import_asset_id",
        "content_hash",
        "availability",
        "retention_class",
        "created_by_id",
        "created_at",
        "updated_at",
        "signal_type",
        "signal_platform",
        "signal_external_id",
        "signal_captured_at",
        "signal_created_by_id",
        "signal_created_at",
        "signal_updated_at",
        "source_content_platform",
        "source_content_external_id",
        "source_content_canonical_url",
        "source_content_author_public_name",
        "source_content_title",
        "source_content_original_text",
        "source_content_public_published_at",
        "source_content_language",
        "source_content_captured_at",
        "source_content_hash",
        "source_content_created_by_id",
        "source_content_created_at",
        "source_content_updated_at",
    }
)


def frozen_source_evidence_errors(rows, *, organization_id) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return ["evidence: at least one frozen evidence row is required"]
    errors = []
    identities = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != FROZEN_SOURCE_EVIDENCE_FIELDS:
            errors.append(f"evidence.{index}: fields do not match the canonical schema")
            continue
        identities.append(row["id"])
        if row["schema"] != "SOURCE_EVIDENCE_SNAPSHOT_V1":
            errors.append(f"evidence.{index}.schema: unsupported schema")
        if row["organization_id"] != str(organization_id):
            errors.append(f"evidence.{index}.organization_id: organization mismatch")
        if not isinstance(row["id"], str) or not row["id"]:
            errors.append(f"evidence.{index}.id: identity is required")
        if not isinstance(row["source_signal_id"], str) or not row["source_signal_id"]:
            errors.append(f"evidence.{index}.source_signal_id: provenance is required")
        if not isinstance(row["original_text"], str):
            errors.append(f"evidence.{index}.original_text: original text is required")
        if not isinstance(row["source_url"], str) or not row["source_url"]:
            errors.append(f"evidence.{index}.source_url: source URL is required")
        if not isinstance(row["content_hash"], str) or len(row["content_hash"]) != 64:
            errors.append(f"evidence.{index}.content_hash: content hash is invalid")
    if len(identities) != len(set(identities)):
        errors.append("evidence: identities must be unique")
    return errors


def _evidence_ids_schema() -> dict[str, object]:
    return {
        "type": "array",
        "items": {"type": "string", "pattern": UUID_PATTERN},
        "minItems": 1,
        "uniqueItems": True,
    }


LEAD_ANALYSIS_OUTPUT_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "company_name": {"type": "string", "maxLength": 255},
        "company_domain": {"type": "string", "maxLength": 253},
        "country_hint": {"type": "string", "maxLength": 64},
        "need_summary_zh": {"type": "string", "minLength": 1, "maxLength": 4000},
        "need_summary_en": {"type": "string", "minLength": 1, "maxLength": 4000},
        "dimensions": {
            "type": "object",
            "properties": {
                "intent": {"type": "integer", "minimum": 0, "maximum": 30},
                "company_fit": {"type": "integer", "minimum": 0, "maximum": 25},
                "specificity": {"type": "integer", "minimum": 0, "maximum": 20},
                "capability_fit": {"type": "integer", "minimum": 0, "maximum": 15},
                "recency": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "required": [
                "intent",
                "company_fit",
                "specificity",
                "capability_fit",
                "recency",
            ],
            "additionalProperties": False,
        },
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "minLength": 1, "maxLength": 128},
                    "value": {"type": "string", "maxLength": 500},
                    "unit": {"type": "string", "maxLength": 64},
                    "evidence_ids": _evidence_ids_schema(),
                },
                "required": ["type", "value", "unit", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "capability_matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capability_code": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                    },
                    "knowledge_evidence_ids": _evidence_ids_schema(),
                    "source_evidence_ids": _evidence_ids_schema(),
                },
                "required": [
                    "capability_code",
                    "knowledge_evidence_ids",
                    "source_evidence_ids",
                ],
                "additionalProperties": False,
            },
        },
        "reasons": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "evidence_ids": _evidence_ids_schema(),
                },
                "required": ["text", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "confidence": {
            "type": "object",
            "properties": {
                "intent": {"type": "number", "minimum": 0, "maximum": 1},
                "company_fit": {"type": "number", "minimum": 0, "maximum": 1},
                "capability": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["intent", "company_fit", "capability"],
            "additionalProperties": False,
        },
        "insufficient_evidence": {"type": "boolean"},
    },
    "required": [
        "company_name",
        "need_summary_zh",
        "need_summary_en",
        "dimensions",
        "requirements",
        "capability_matches",
        "reasons",
        "confidence",
        "insufficient_evidence",
    ],
    "additionalProperties": False,
}


_validator_class = validator_for(LEAD_ANALYSIS_OUTPUT_SCHEMA)
_validator_class.check_schema(LEAD_ANALYSIS_OUTPUT_SCHEMA)
_validator = _validator_class(LEAD_ANALYSIS_OUTPUT_SCHEMA)


def _path(error) -> str:
    return ".".join(str(part) for part in error.absolute_path) or "$"


def _normalized_claim_text(value) -> str:
    return (
        re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value)))
        .strip()
        .casefold()
    )


def _claim_is_in_cited_evidence(value, evidence_ids, evidence_text_by_id) -> bool:
    claim = _normalized_claim_text(value)
    return bool(claim) and any(
        claim in evidence_text_by_id.get(str(evidence_id), "")
        for evidence_id in evidence_ids
    )


def _capability_is_supported(code, evidence_ids, evidence_text_by_id) -> bool:
    if not re.match(r"^cap(?:ability)?[-_]", str(code), re.IGNORECASE):
        return True
    generic = {"cap", "capability", "gear", "gears"}
    discriminating = [
        token
        for token in re.split(r"[^a-z0-9]+", str(code).casefold())
        if len(token) >= 3 and token not in generic
    ]
    if not discriminating:
        return False
    cited = "\n".join(
        evidence_text_by_id.get(str(evidence_id), "") for evidence_id in evidence_ids
    )
    return any(token in cited for token in discriminating)


def lead_analysis_errors(output, *, snapshot=None) -> list[str]:
    errors = [
        f"{_path(error)}: {error.message}"
        for error in sorted(
            _validator.iter_errors(output), key=lambda item: list(item.absolute_path)
        )
    ]
    if errors or snapshot is None or not isinstance(output, dict):
        return errors
    if not isinstance(snapshot, dict):
        return ["$: frozen analysis snapshot is invalid"]

    source_evidence_ids = {
        str(row.get("id"))
        for row in snapshot.get("evidence", [])
        if isinstance(row, dict) and row.get("id")
    }
    evidence_text_by_id = {
        str(row.get("id")): _normalized_claim_text(row.get("original_text", ""))
        for row in snapshot.get("evidence", [])
        if isinstance(row, dict) and row.get("id")
    }
    concepts = snapshot.get("ontology_snapshot", {}).get("concept_versions", [])
    requirement_codes = {
        str(row.get("code"))
        for row in concepts
        if isinstance(row, dict) and row.get("concept_type") == "REQUIREMENT"
    }
    capability_codes = {
        str(row.get("code"))
        for row in concepts
        if isinstance(row, dict) and row.get("concept_type") == "CAPABILITY"
    }
    capability_bindings = {
        str(row.get("capability_code")): {
            str(item) for item in row.get("knowledge_evidence_ids", [])
        }
        for row in snapshot.get("capability_bindings", [])
        if isinstance(row, dict) and row.get("capability_code")
    }
    frozen_candidate = snapshot.get("candidate")
    if not isinstance(frozen_candidate, dict):
        errors.append("$: frozen candidate facts are invalid")
    else:
        for field_name in ("company_name", "company_domain", "country_hint"):
            supplied = output.get(field_name, "")
            frozen_value = frozen_candidate.get(field_name, "")
            if supplied != frozen_value:
                errors.append(
                    f"{field_name}: value must preserve the frozen candidate fact or remain blank"
                )

    for index, requirement in enumerate(output["requirements"]):
        if requirement["type"] not in requirement_codes:
            errors.append(f"requirements.{index}.type: unknown frozen requirement code")
        if not set(requirement["evidence_ids"]) <= source_evidence_ids:
            errors.append(
                f"requirements.{index}.evidence_ids: unknown frozen source evidence"
            )
        if not _claim_is_in_cited_evidence(
            requirement["value"],
            requirement["evidence_ids"],
            evidence_text_by_id,
        ):
            errors.append(
                f"requirements.{index}.value: value is not present in cited frozen evidence"
            )
        if requirement["unit"] and not _claim_is_in_cited_evidence(
            requirement["unit"],
            requirement["evidence_ids"],
            evidence_text_by_id,
        ):
            errors.append(
                f"requirements.{index}.unit: unit is not present in cited frozen evidence"
            )
    for index, match in enumerate(output["capability_matches"]):
        code = match["capability_code"]
        if code not in capability_codes or code not in capability_bindings:
            errors.append(
                f"capability_matches.{index}.capability_code: unknown frozen capability"
            )
        elif not set(match["knowledge_evidence_ids"]) <= capability_bindings[code]:
            errors.append(
                f"capability_matches.{index}.knowledge_evidence_ids: evidence is not bound to the frozen capability"
            )
        if not set(match["source_evidence_ids"]) <= source_evidence_ids:
            errors.append(
                f"capability_matches.{index}.source_evidence_ids: unknown frozen source evidence"
            )
        elif not _capability_is_supported(
            code,
            match["source_evidence_ids"],
            evidence_text_by_id,
        ):
            errors.append(
                f"capability_matches.{index}.capability_code: capability is not supported by cited frozen evidence"
            )
    for index, reason in enumerate(output["reasons"]):
        if not set(reason["evidence_ids"]) <= source_evidence_ids:
            errors.append(
                f"reasons.{index}.evidence_ids: unknown frozen source evidence"
            )
    if output["insufficient_evidence"] and (
        output["requirements"] or output["capability_matches"]
    ):
        errors.append(
            "insufficient_evidence: requirements and capability matches must be empty"
        )
    return errors


__all__ = [
    "FROZEN_SOURCE_EVIDENCE_FIELDS",
    "LEAD_ANALYSIS_OUTPUT_SCHEMA",
    "frozen_source_evidence_errors",
    "lead_analysis_errors",
]
