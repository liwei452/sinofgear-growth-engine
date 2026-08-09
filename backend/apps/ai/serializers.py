import json
import re
import unicodedata

from rest_framework import serializers

from apps.campaigns.generation_schema import CONTENT_GENERATION_INPUT_SCHEMA
from apps.common.security import normalize_persisted_error

from .models import AIRun


_MAX_AUDIT_DEPTH = 6
_MAX_AUDIT_KEYS = 24
_MAX_AUDIT_ITEMS = 20
_MAX_AUDIT_STRING_LENGTH = 256
_MAX_AUDIT_VALUE_BYTES = 8_192
_TRUNCATED = "[TRUNCATED]"

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "cta": {"type": "string"},
        "concept_codes": {"type": "array", "items": {"type": "string"}},
        "platform_code": {"type": "string"},
    },
}
_PROVIDER_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "provider_code": {"type": "string"},
        "model": {"type": "string"},
        "request_id": {"type": "string"},
        "finish_reason": {"type": "string"},
        "input_tokens": {"type": "integer"},
        "output_tokens": {"type": "integer"},
        "total_tokens": {"type": "integer"},
        "latency_ms": {"type": "number"},
    },
}

_SENSITIVE_NAME = (
    r"(?:authorization|api[\s_-]*key|access[\s_-]*token|refresh[\s_-]*token|"
    r"client[\s_-]*secret|password|passwd|passphrase|set[\s_-]*cookie|cookie|token)"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    rf"(?<![\w]){_SENSITIVE_NAME}\s*(?::|=|%3a|%3d)", re.IGNORECASE
)
_AUTHORIZATION_SCHEME = re.compile(
    r"(?<![\w])authorization\s*(?:(?::|=|%3a|%3d)\s*)?(?:basic|bearer)\b",
    re.IGNORECASE,
)


def _redact_and_bound_string(value: str) -> str:
    detection_value = unicodedata.normalize("NFKC", value).casefold()
    if (
        _SENSITIVE_ASSIGNMENT.search(detection_value)
        or _AUTHORIZATION_SCHEME.search(detection_value)
    ):
        return "[REDACTED]"
    if len(value) > _MAX_AUDIT_STRING_LENGTH:
        return f"{value[:_MAX_AUDIT_STRING_LENGTH - len(_TRUNCATED)]}{_TRUNCATED}"
    return value


def _schema_variant(schema: dict[str, object], value) -> dict[str, object]:
    variants = schema.get("oneOf")
    if not isinstance(variants, list):
        return schema
    expected = "null" if value is None else "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "string"
    for variant in variants:
        if isinstance(variant, dict) and variant.get("type") == expected:
            return variant
    return {}


def _contains_truncation(value) -> bool:
    if isinstance(value, dict):
        return value.get("_truncated") is True or any(
            _contains_truncation(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_truncation(item) for item in value)
    return isinstance(value, str) and _TRUNCATED in value


def _allowlisted_summary(value, schema: dict[str, object], *, depth: int = 0):
    if depth >= _MAX_AUDIT_DEPTH:
        return {"_truncated": True}

    schema = _schema_variant(schema, value)
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            return None
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        result = {}
        allowed_items = [(key, properties[key]) for key in value if key in properties]
        for key, child_schema in allowed_items[:_MAX_AUDIT_KEYS]:
            if isinstance(child_schema, dict):
                result[key] = _allowlisted_summary(value[key], child_schema, depth=depth + 1)
        if len(allowed_items) > _MAX_AUDIT_KEYS or _contains_truncation(result):
            result["_truncated"] = True
        return result

    if schema_type == "array":
        if not isinstance(value, (list, tuple)):
            return []
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return []
        result = [
            _allowlisted_summary(item, item_schema, depth=depth + 1)
            for item in value[:_MAX_AUDIT_ITEMS]
        ]
        if len(value) > _MAX_AUDIT_ITEMS:
            result.append(_TRUNCATED)
        return result

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_and_bound_string(value)
    return None


def _bounded_summary(value, schema: dict[str, object]):
    summary = _allowlisted_summary(value, schema)
    if len(json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode()) <= _MAX_AUDIT_VALUE_BYTES:
        return summary
    return {"_truncated": True}


class AIRunSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(read_only=True)
    prompt = serializers.SerializerMethodField()
    reviewer = serializers.SerializerMethodField()
    input_snapshot = serializers.SerializerMethodField()
    output_json = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    provider_metadata = serializers.SerializerMethodField()
    human_correction = serializers.SerializerMethodField()

    class Meta:
        model = AIRun
        fields = [
            "id", "job_id", "job_attempt", "status", "prompt", "provider", "model",
            "confidence", "human_correction", "reviewer", "created_at", "started_at",
            "finished_at", "reviewed_at", "input_snapshot", "output_json", "error",
            "provider_metadata",
        ]
        read_only_fields = fields

    def get_prompt(self, run: AIRun) -> dict[str, object]:
        prompt = run.prompt_version
        return {
            "purpose": prompt.purpose,
            "code": prompt.code,
            "version": prompt.version,
            "provider": prompt.provider,
            "model": prompt.model,
        }

    def get_reviewer(self, run: AIRun) -> dict[str, object] | None:
        if run.reviewed_by_id is None:
            return None
        return {"id": run.reviewed_by_id, "username": run.reviewed_by.get_username()}

    def get_input_snapshot(self, run: AIRun):
        return _bounded_summary(run.input_snapshot, CONTENT_GENERATION_INPUT_SCHEMA)

    def get_output_json(self, run: AIRun):
        return _bounded_summary(run.output_json, _OUTPUT_SCHEMA)

    def get_error(self, run: AIRun):
        if run.error is None:
            return None
        return normalize_persisted_error(run.error)

    def get_provider_metadata(self, run: AIRun):
        summary = _bounded_summary(run.provider_metadata, _PROVIDER_METADATA_SCHEMA)
        if not isinstance(summary, dict):
            return {}
        return {
            key: value for key, value in summary.items()
            if not (isinstance(value, str) and "[REDACTED]" in value)
        }

    def get_human_correction(self, run: AIRun):
        return _bounded_summary(run.human_correction, _OUTPUT_SCHEMA)


class AIRunListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AIRunSerializer(many=True)


class AIRunFilterSerializer(serializers.Serializer):
    job = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=AIRun.Status.choices, required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class AIRunValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
