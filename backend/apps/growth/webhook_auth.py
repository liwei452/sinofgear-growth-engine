"""HMAC verification for inbound website webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time


WEBHOOK_TIMESTAMP_WINDOW_SECONDS = 300


def verify_webhook_signature(
    *,
    secret: str,
    timestamp: str,
    signature: str,
    payload,
) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - timestamp_int) > WEBHOOK_TIMESTAMP_WINDOW_SECONDS:
        return False
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{canonical}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return secrets.compare_digest(expected, signature)
