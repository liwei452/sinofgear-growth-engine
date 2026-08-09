import json


MAX_CONTENT_JSON_BYTES = 65_536
MAX_CONCEPT_CODES = 100
MAX_CONCEPT_CODE_CHARS = 256
TEXT_LIMITS = {"title": 500, "body": 50_000, "cta": 2_000}

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


def validate_content_payload(payload, *, platform_code=None):
    expected = set(MASTER_PAYLOAD_SCHEMA["required"])
    if platform_code is not None:
        expected.add("platform_code")
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Content payload does not match the exact schema.")
    cleaned = {}
    for name, limit in TEXT_LIMITS.items():
        value = payload[name]
        if not isinstance(value, str) or not (value := value.strip()) or len(value) > limit:
            raise ValueError("Content text fields must be nonempty and bounded.")
        cleaned[name] = value
    codes = payload["concept_codes"]
    if not isinstance(codes, list) or len(codes) > MAX_CONCEPT_CODES:
        raise ValueError("Concept codes must be a bounded list.")
    normalized_codes = []
    for code in codes:
        if (
            not isinstance(code, str)
            or not (code := code.strip())
            or len(code) > MAX_CONCEPT_CODE_CHARS
            or code in normalized_codes
        ):
            raise ValueError("Concept codes must be unique, nonempty, and bounded.")
        normalized_codes.append(code)
    cleaned["concept_codes"] = normalized_codes
    if platform_code is not None:
        if (
            not isinstance(platform_code, str)
            or not platform_code
            or len(platform_code) > 64
            or payload["platform_code"] != platform_code
        ):
            raise ValueError("Platform identity cannot change in content payload.")
        cleaned["platform_code"] = platform_code
    if len(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_CONTENT_JSON_BYTES:
        raise ValueError("Content payload exceeds the total JSON byte limit.")
    return cleaned
