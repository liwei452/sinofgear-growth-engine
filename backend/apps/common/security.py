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
        "tokenbudget", "credentialtype",
    }
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
    return deepcopy(value)
