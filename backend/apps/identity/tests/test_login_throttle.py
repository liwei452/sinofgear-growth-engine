from django.contrib.auth import get_user_model
from django.core.cache.backends.locmem import LocMemCache

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle


@pytest.mark.django_db
def test_login_is_rate_limited_after_repeated_attempts(monkeypatch) -> None:
    # DRF snapshots DEFAULT_THROTTLE_RATES and the default cache onto the
    # throttle class at import time, so override_settings cannot touch them.
    # Replace both in place (monkeypatch restores them afterwards).
    monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", {"login": "3/min"})
    monkeypatch.setattr(
        SimpleRateThrottle, "cache", LocMemCache("login-throttle-test", {})
    )
    get_user_model().objects.create_user(username="throttle-user", password="safe-password")
    client = APIClient()
    credentials = {"username": "throttle-user", "password": "wrong"}

    statuses = [
        client.post("/api/v1/auth/login", credentials, format="json").status_code
        for _ in range(4)
    ]

    assert statuses[:3] == [400, 400, 400]
    assert statuses[3] == 429
