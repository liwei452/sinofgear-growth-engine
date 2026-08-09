import re
from copy import deepcopy


_SECRET_KEYS = frozenset(
    {
        "token", "tokens", "accesstoken", "refreshtoken", "secrettoken", "password",
        "passphrase", "apikey", "authorization", "cookie", "cookies",
        "privatekey", "clientsecret", "secret",
    }
)


def scrub_secrets(value):
    """Return a deep, JSON-shaped copy with recursively sensitive keys removed."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in _SECRET_KEYS:
                continue
            cleaned[key] = scrub_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_secrets(item) for item in value]
    return deepcopy(value)
