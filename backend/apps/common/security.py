import re
from copy import deepcopy


_SECRET_KEYS = frozenset(
    {
        "token", "tokens", "accesstoken", "refreshtoken", "secrettoken", "password",
        "passphrase", "apikey", "authorization", "cookie", "cookies",
        "privatekey", "clientsecret", "secret",
    }
)

_SECRET_KEY_FRAGMENTS = frozenset(
    {
        "accesstoken", "refreshtoken", "authtoken", "secrettoken",
        "apikey", "authorization", "password", "passwd", "passphrase",
        "sessioncookie", "privatekey", "clientsecret", "credential",
    }
)
_SECRET_KEY_SEGMENTS = frozenset(
    {
        "token", "tokens", "password", "passwd", "passphrase",
        "authorization", "cookie", "cookies", "secret", "credential",
        "credentials", "pem",
    }
)
_SAFE_KEYS = frozenset(
    {
        "publictokencount", "passwordpolicy", "safetokenizedname",
        "tokenbudget", "credentialtype", "inputtokens", "outputtokens",
        "totaltokens", "cachehittokens",
    }
)

_CONTROLLED_ERROR_MESSAGES = {
    "job_error": "Job execution failed.",
    "provider_error": "AI provider generation failed.",
    "invalid_provider_output": "Provider output did not match the required schema.",
    "output_too_large": "Provider output exceeds the size limit.",
    "ai_run_start_failed": "AI audit run could not start.",
    "job_canceled": "Job was canceled.",
    "content_finalize_failed": "Generated content could not be finalized.",
    "SOURCE_IMPORT_FAILED": "Public source import failed.",
}

_SECRET_VALUE = re.compile(
    r"(?i)(?:\bauthorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+|"
    r"\bbearer\s+sk-[a-z0-9_-]{8,}|\bsk-[a-z0-9_-]{8,})"
)


def is_sensitive_key(key) -> bool:
    raw_key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    segments = [
        item for item in re.split(r"[^a-z0-9]+", raw_key.casefold()) if item
    ]
    normalized = "".join(segments)
    if normalized in _SAFE_KEYS:
        return False
    return normalized in _SECRET_KEYS or any(
        fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS
    ) or bool(set(segments) & _SECRET_KEY_SEGMENTS)


def scrub_secrets(value):
    """Return a deep, JSON-shaped copy with recursively sensitive keys removed."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if is_sensitive_key(key):
                continue
            cleaned[key] = scrub_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return "[REDACTED]"
    return deepcopy(value)


def normalize_persisted_error(value) -> dict[str, str]:
    """Return the strict, controlled error shape allowed in audit records."""
    code = value.get("code") if isinstance(value, dict) else None
    if not isinstance(code, str) or code not in _CONTROLLED_ERROR_MESSAGES:
        code = "job_error"
    return {"code": code, "message": _CONTROLLED_ERROR_MESSAGES[code]}
