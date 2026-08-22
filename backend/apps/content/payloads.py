import json
import re


MAX_CONTENT_JSON_BYTES = 65_536
MAX_CONCEPT_CODES = 100
MAX_CONCEPT_CODE_CHARS = 256
MAX_HASHTAGS = 30
MAX_EVIDENCE_FACT_IDS = 100
MAX_PLATFORM_VARIANTS = 12
MAX_SHOTS = 24
TEXT_LIMITS = {"title": 500, "body": 50_000, "cta": 2_000}
NUMERIC_CLAIM_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:mm|cm|µm|um|micron|microns|%|°|hrc|hrb|kw|rpm|kg|ton|teeth?|modules?)\b",
    re.IGNORECASE,
)
HTTPS_URL_PATTERN = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)
COMMON_V2_TEXT_LIMITS = {
    **TEXT_LIMITS,
    "language": 16,
    "landing_page_url": 2_000,
}
TIKTOK_TEXT_LIMITS = {
    "script": 50_000,
    "voiceover": 50_000,
    "subtitles": 50_000,
    "voiceover_language": 16,
    "subtitle_language": 16,
}

MASTER_PAYLOAD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "body", "cta", "concept_codes"],
    "properties": {
        **{
            name: {"type": "string", "minLength": 1, "maxLength": limit}
            for name, limit in TEXT_LIMITS.items()
        },
        "concept_codes": {
            "type": "array",
            "maxItems": MAX_CONCEPT_CODES,
            "uniqueItems": True,
            "items": {
                "type": "string", "minLength": 1,
                "maxLength": MAX_CONCEPT_CODE_CHARS,
            },
        },
    },
}
PLATFORM_PAYLOAD_SCHEMA = {
    **MASTER_PAYLOAD_SCHEMA,
    "required": [*MASTER_PAYLOAD_SCHEMA["required"], "platform_code"],
    "properties": {
        **MASTER_PAYLOAD_SCHEMA["properties"],
        "platform_code": {"type": "string", "minLength": 1, "maxLength": 64},
    },
}

STRING_LIST_SCHEMA = {
    "type": "array",
    "uniqueItems": True,
    "items": {"type": "string", "minLength": 1, "maxLength": 256},
}
PLATFORM_VARIANT_V2_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "platform_code", "language", "title", "body", "cta",
        "landing_page_url", "hashtags", "evidence_fact_ids",
    ],
    "properties": {
        "platform_code": {"type": "string", "minLength": 1, "maxLength": 64},
        **{
            name: {"type": "string", "minLength": 1, "maxLength": limit}
            for name, limit in COMMON_V2_TEXT_LIMITS.items()
        },
        "hashtags": {**STRING_LIST_SCHEMA, "maxItems": MAX_HASHTAGS},
        "evidence_fact_ids": {
            **STRING_LIST_SCHEMA, "minItems": 1, "maxItems": MAX_EVIDENCE_FACT_IDS,
        },
    },
}
TIKTOK_VARIANT_V2_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        *PLATFORM_VARIANT_V2_SCHEMA["required"],
        "duration_seconds", "aspect_ratio", "script", "shot_list",
        "voiceover", "voiceover_language", "subtitles", "subtitle_language",
    ],
    "properties": {
        **PLATFORM_VARIANT_V2_SCHEMA["properties"],
        "duration_seconds": {"type": "integer", "minimum": 15, "maximum": 60},
        "aspect_ratio": {"const": "9:16"},
        **{
            name: {"type": "string", "minLength": 1, "maxLength": limit}
            for name, limit in TIKTOK_TEXT_LIMITS.items()
        },
        "shot_list": {
            "type": "array", "minItems": 1, "maxItems": MAX_SHOTS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["scene", "visual", "on_screen_text"],
                "properties": {
                    "scene": {"type": "string", "minLength": 1, "maxLength": 64},
                    "visual": {"type": "string", "minLength": 1, "maxLength": 2_000},
                    "on_screen_text": {
                        "type": "string", "minLength": 1, "maxLength": 1_000,
                    },
                },
            },
        },
    },
}
CONTENT_OUTPUT_SCHEMA_V2 = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "language", "title", "body", "cta",
        "landing_page_url", "concept_codes", "evidence_fact_ids",
        "platform_variants",
    ],
    "properties": {
        "schema_version": {"const": 2},
        **{
            name: {"type": "string", "minLength": 1, "maxLength": limit}
            for name, limit in COMMON_V2_TEXT_LIMITS.items()
        },
        "concept_codes": {
            **STRING_LIST_SCHEMA, "maxItems": MAX_CONCEPT_CODES,
        },
        "evidence_fact_ids": {
            **STRING_LIST_SCHEMA, "minItems": 1, "maxItems": MAX_EVIDENCE_FACT_IDS,
        },
        "platform_variants": {
            "type": "array", "minItems": 1, "maxItems": MAX_PLATFORM_VARIANTS,
            "items": {
                "oneOf": [PLATFORM_VARIANT_V2_SCHEMA, TIKTOK_VARIANT_V2_SCHEMA],
            },
        },
    },
}


def _bounded_text(value, *, limit, label="Content text"):
    if not isinstance(value, str) or not (value := value.strip()) or len(value) > limit:
        raise ValueError(f"{label} fields must be nonempty and bounded.")
    return value


def _unique_text_list(value, *, limit, item_limit=256, label):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be a bounded list.")
    cleaned = []
    for item in value:
        item = _bounded_text(item, limit=item_limit, label=label)
        if item in cleaned:
            raise ValueError(f"{label} must contain unique values.")
        cleaned.append(item)
    return cleaned


def _validate_legacy_payload(payload, *, platform_code=None):
    expected = set(MASTER_PAYLOAD_SCHEMA["required"])
    if platform_code is not None:
        expected.add("platform_code")
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Content payload does not match the exact schema.")
    cleaned = {
        name: _bounded_text(payload[name], limit=limit)
        for name, limit in TEXT_LIMITS.items()
    }
    cleaned["concept_codes"] = _unique_text_list(
        payload["concept_codes"], limit=MAX_CONCEPT_CODES,
        item_limit=MAX_CONCEPT_CODE_CHARS, label="Concept codes",
    )
    if platform_code is not None:
        if (
            not isinstance(platform_code, str)
            or not platform_code
            or len(platform_code) > 64
            or payload["platform_code"] != platform_code
        ):
            raise ValueError("Platform identity cannot change in content payload.")
        cleaned["platform_code"] = platform_code
    return cleaned


def _validate_shot_list(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SHOTS:
        raise ValueError("TikTok payload shot list must be nonempty and bounded.")
    cleaned = []
    for shot in value:
        if not isinstance(shot, dict) or set(shot) != {"scene", "visual", "on_screen_text"}:
            raise ValueError("TikTok payload shot does not match the exact schema.")
        cleaned.append({
            "scene": _bounded_text(shot["scene"], limit=64, label="TikTok payload"),
            "visual": _bounded_text(shot["visual"], limit=2_000, label="TikTok payload"),
            "on_screen_text": _bounded_text(
                shot["on_screen_text"], limit=1_000, label="TikTok payload"
            ),
        })
    return cleaned


def _validate_platform_v2(payload, *, platform_code=None):
    if not isinstance(payload, dict):
        raise ValueError("Platform payload does not match the exact schema.")
    actual_code = payload.get("platform_code")
    expected_keys = {
        "schema_version", "platform_code", "language", "title", "body", "cta",
        "landing_page_url", "hashtags", "evidence_fact_ids",
    }
    if actual_code == "TIKTOK":
        expected_keys |= {
            "duration_seconds", "aspect_ratio", "script", "shot_list",
            "voiceover", "voiceover_language", "subtitles", "subtitle_language",
        }
    if set(payload) != expected_keys or payload.get("schema_version") != 2:
        raise ValueError("Platform payload does not match the exact schema.")
    if platform_code is not None and actual_code != platform_code:
        raise ValueError("Platform identity cannot change in content payload.")
    cleaned = {
        "schema_version": 2,
        "platform_code": _bounded_text(actual_code, limit=64, label="Platform payload"),
    }
    for name, limit in COMMON_V2_TEXT_LIMITS.items():
        cleaned[name] = _bounded_text(payload[name], limit=limit, label="Platform payload")
    cleaned["hashtags"] = _unique_text_list(
        payload["hashtags"], limit=MAX_HASHTAGS, label="Hashtags",
    )
    cleaned["evidence_fact_ids"] = _unique_text_list(
        payload["evidence_fact_ids"], limit=MAX_EVIDENCE_FACT_IDS,
        label="Evidence fact identifiers",
    )
    if actual_code == "TIKTOK":
        duration = payload["duration_seconds"]
        if isinstance(duration, bool) or not isinstance(duration, int) or not 15 <= duration <= 60:
            raise ValueError("TikTok payload duration must be between 15 and 60 seconds.")
        if payload["aspect_ratio"] != "9:16":
            raise ValueError("TikTok payload aspect ratio must be 9:16.")
        cleaned.update({"duration_seconds": duration, "aspect_ratio": "9:16"})
        for name, limit in TIKTOK_TEXT_LIMITS.items():
            cleaned[name] = _bounded_text(payload[name], limit=limit, label="TikTok payload")
        cleaned["shot_list"] = _validate_shot_list(payload["shot_list"])
    return cleaned


def _validate_master_v2(payload):
    if not isinstance(payload, dict):
        raise ValueError("Content payload does not match the exact schema.")
    required = {
        "schema_version", "language", "title", "body", "cta", "landing_page_url",
        "concept_codes", "evidence_fact_ids", "platform_variants",
    }
    allowed = required | {"internal_translation_zh"}
    if set(payload) < required or not set(payload) <= allowed or payload.get("schema_version") != 2:
        raise ValueError("Content payload does not match the exact schema.")
    cleaned = {"schema_version": 2}
    for name, limit in COMMON_V2_TEXT_LIMITS.items():
        cleaned[name] = _bounded_text(payload[name], limit=limit)
    cleaned["concept_codes"] = _unique_text_list(
        payload["concept_codes"], limit=MAX_CONCEPT_CODES,
        item_limit=MAX_CONCEPT_CODE_CHARS, label="Concept codes",
    )
    cleaned["evidence_fact_ids"] = _unique_text_list(
        payload["evidence_fact_ids"], limit=MAX_EVIDENCE_FACT_IDS,
        label="Evidence fact identifiers",
    )
    if "internal_translation_zh" in payload:
        cleaned["internal_translation_zh"] = _bounded_text(
            payload["internal_translation_zh"], limit=50_000,
            label="Internal Chinese translation",
        )
    variants = payload["platform_variants"]
    if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_PLATFORM_VARIANTS:
        raise ValueError("Content platform variants must be a nonempty bounded list.")
    cleaned["platform_variants"] = []
    for variant in variants:
        if not isinstance(variant, dict) or "schema_version" in variant:
            raise ValueError("Generated platform variant does not match the exact schema.")
        normalized = _validate_platform_v2({"schema_version": 2, **variant})
        normalized.pop("schema_version")
        cleaned["platform_variants"].append(normalized)
    return cleaned


def validate_generated_content_output(payload, snapshot):
    if isinstance(payload, dict) and "internal_translation_zh" in payload:
        raise ValueError("Generated content must not include internal_translation_zh.")
    cleaned = _validate_master_v2(payload)
    target_language = snapshot.get("language")
    if cleaned["language"] != target_language:
        raise ValueError("Generated publication language does not match the brief language.")
    expected_platforms = [row.get("code") for row in snapshot.get("target_platforms", [])]
    actual_platforms = [row["platform_code"] for row in cleaned["platform_variants"]]
    if actual_platforms != expected_platforms or len(actual_platforms) != len(set(actual_platforms)):
        raise ValueError("Generated platform variants do not match the selected platforms.")
    allowed_facts = {
        str(row.get("fact_id")) for row in snapshot.get("verified_product_facts", [])
        if row.get("fact_id")
    }
    seller = snapshot.get("agent_context", {}).get("seller", {})
    allowed_facts.update(
        str(row.get("fact_id"))
        for row in seller.get("public_claims", [])
        if isinstance(row, dict) and row.get("fact_id")
    )
    if not cleaned["evidence_fact_ids"]:
        raise ValueError("Generated evidence references must contain at least one fact.")
    if not set(cleaned["evidence_fact_ids"]) <= allowed_facts:
        raise ValueError("Generated evidence references contain an unknown fact.")
    expected_landing_page = snapshot.get("landing_page_url")
    if cleaned["landing_page_url"] != expected_landing_page:
        raise ValueError("Generated landing page does not match the frozen brief.")
    allowed_concepts = {
        str(row.get("code"))
        for row in snapshot.get("ontology_snapshot", {}).get("concept_versions", [])
        if row.get("status") == "APPROVED" and row.get("code")
    }
    if not set(cleaned["concept_codes"]) <= allowed_concepts:
        raise ValueError("Generated concept references contain unapproved knowledge.")
    bodies = []
    for variant in cleaned["platform_variants"]:
        if variant["language"] != target_language:
            raise ValueError("Generated platform language does not match the brief language.")
        if variant["evidence_fact_ids"] != cleaned["evidence_fact_ids"]:
            raise ValueError("Generated platform evidence must inherit the master evidence.")
        if variant["landing_page_url"] != expected_landing_page:
            raise ValueError("Generated platform landing page does not match the frozen brief.")
        normalized_body = variant["body"].casefold()
        if normalized_body in bodies:
            raise ValueError("Generated platform variants must contain adapted platform copy.")
        bodies.append(normalized_body)
        if variant["platform_code"] == "TIKTOK" and (
            variant["voiceover_language"] != target_language
            or variant["subtitle_language"] != target_language
        ):
            raise ValueError("TikTok language metadata must match the publication language.")
    _assert_no_prohibited_claims(cleaned, snapshot)
    _assert_urls_verified(cleaned, snapshot)
    _assert_numeric_claims_grounded(cleaned, snapshot)
    _ensure_json_limit(cleaned)
    return cleaned


def validate_snapshot_bound_platform_output(payload, snapshot, *, platform_code):
    """Revalidate an editable platform revision against its frozen Job snapshot."""

    cleaned = _validate_platform_v2(payload, platform_code=platform_code)
    if cleaned["language"] != snapshot.get("language"):
        raise ValueError("Generated platform language does not match the brief language.")
    allowed_facts = {
        str(row.get("fact_id"))
        for row in snapshot.get("verified_product_facts", [])
        if isinstance(row, dict) and row.get("fact_id")
    }
    seller = snapshot.get("agent_context", {}).get("seller", {})
    allowed_facts.update(
        str(row.get("fact_id"))
        for row in seller.get("public_claims", [])
        if isinstance(row, dict) and row.get("fact_id")
    )
    if not cleaned["evidence_fact_ids"] or not set(
        cleaned["evidence_fact_ids"]
    ) <= allowed_facts:
        raise ValueError("Generated evidence references contain an unknown fact.")
    if cleaned["landing_page_url"] != snapshot.get("landing_page_url"):
        raise ValueError("Generated landing page does not match the frozen brief.")
    _assert_no_prohibited_claims(cleaned, snapshot)
    _assert_urls_verified(cleaned, snapshot)
    _assert_numeric_claims_grounded(cleaned, snapshot)
    _ensure_json_limit(cleaned)
    return cleaned


def platform_variant_payload(master_payload, platform_code):
    master = _validate_master_v2(master_payload)
    matches = [
        row for row in master["platform_variants"]
        if row["platform_code"] == platform_code
    ]
    if len(matches) != 1:
        raise ValueError("Generated platform variant is missing or duplicated.")
    variant = _validate_platform_v2({"schema_version": 2, **matches[0]}, platform_code=platform_code)
    _ensure_json_limit(variant)
    return variant


def _ensure_json_limit(cleaned):
    if len(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_CONTENT_JSON_BYTES:
        raise ValueError("Content payload exceeds the total JSON byte limit.")


def _platform_claim_scan_text_fields(variant):
    code = variant.get("platform_code", "UNKNOWN")
    fields = [
        (f"platform:{code}:{name}", variant.get(name, ""))
        for name in ("title", "body", "cta")
    ]
    for index, hashtag in enumerate(variant.get("hashtags", []), start=1):
        fields.append((f"platform:{code}:hashtag:{index}", hashtag))
    if code == "TIKTOK":
        for name in ("script", "voiceover", "subtitles"):
            fields.append((f"platform:TIKTOK:{name}", variant.get(name, "")))
        for index, shot in enumerate(variant.get("shot_list", []), start=1):
            if isinstance(shot, dict):
                for name in ("scene", "visual", "on_screen_text"):
                    fields.append(
                        (f"platform:TIKTOK:shot:{index}:{name}", shot.get(name, ""))
                    )
    return fields


def _claim_scan_text_fields(cleaned):
    """Return every user-facing text field as ``(label, text)`` pairs."""
    if cleaned.get("platform_code"):
        return _platform_claim_scan_text_fields(cleaned)
    fields = [(name, cleaned[name]) for name in ("title", "body", "cta")]
    for variant in cleaned.get("platform_variants", []):
        fields.extend(_platform_claim_scan_text_fields(variant))
    return fields


def _assert_no_prohibited_claims(cleaned, snapshot):
    prohibited = [
        claim.strip().casefold()
        for claim in snapshot.get("prohibited_claims", [])
        if isinstance(claim, str) and claim.strip()
    ]
    if not prohibited:
        return
    for label, text in _claim_scan_text_fields(cleaned):
        folded = text.casefold()
        for claim in prohibited:
            if claim in folded:
                raise ValueError(f"Generated content contains a prohibited claim in {label}.")


def _verified_urls(snapshot):
    urls = {str(snapshot.get("landing_page_url") or "").strip()}
    for page in snapshot.get("agent_context", {}).get("website_pages", []):
        if not isinstance(page, dict):
            continue
        urls.add(str(page.get("canonical_url") or "").strip())
        cta = page.get("primary_cta")
        if isinstance(cta, dict):
            urls.add(str(cta.get("url") or "").strip())
    return {url for url in urls if url}


def _assert_urls_verified(cleaned, snapshot):
    allowed = _verified_urls(snapshot)
    for label, text in _claim_scan_text_fields(cleaned):
        for match in HTTPS_URL_PATTERN.finditer(text):
            url = match.group(0).rstrip(".,;:!?)]}")
            if url not in allowed:
                raise ValueError(
                    f"Generated content contains an unverified URL in {label}."
                )


def _grounding_fact_values(snapshot):
    values = []
    for fact in snapshot.get("verified_product_facts", []):
        if not isinstance(fact, dict):
            continue
        value = fact.get("value")
        if isinstance(value, str) and value.strip():
            folded = value.strip().casefold()
            if len(folded) >= 2:
                values.append(folded)
    return values


def _numeric_claim_sentences(cleaned):
    sentences = []
    for _label, text in _claim_scan_text_fields(cleaned):
        for sentence in re.split(r"[.!?\n]+", text):
            sentence = sentence.strip()
            if sentence and NUMERIC_CLAIM_PATTERN.search(sentence):
                sentences.append(sentence)
    return sentences


def _fact_value_matches(value: str, sentence: str) -> bool:
    if value.isdigit():
        return bool(re.search(rf"(?<!\d){re.escape(value)}(?!\d)", sentence))
    return value in sentence


def _assert_numeric_claims_grounded(cleaned, snapshot):
    """Require numeric/spec claims to trace back to a verified fact value."""
    claim_sentences = _numeric_claim_sentences(cleaned)
    if not claim_sentences:
        return
    fact_values = _grounding_fact_values(snapshot)
    for sentence in claim_sentences:
        folded = sentence.casefold()
        if not any(_fact_value_matches(value, folded) for value in fact_values):
            raise ValueError("Generated content contains a numeric claim without a verified fact.")


def validate_content_payload(payload, *, platform_code=None):
    if isinstance(payload, dict) and payload.get("schema_version") == 2:
        cleaned = (
            _validate_platform_v2(payload, platform_code=platform_code)
            if platform_code is not None else _validate_master_v2(payload)
        )
    else:
        cleaned = _validate_legacy_payload(payload, platform_code=platform_code)
    _ensure_json_limit(cleaned)
    return cleaned
