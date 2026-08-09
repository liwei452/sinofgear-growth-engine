from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Role
from apps.tracking.services import (
    create_short_link, create_tracking_link, record_click_event,
)


def _client(organization, role_code, suffix=""):
    role = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator,
        Role.Code.OPERATOR: Role.objects.create_operator,
        Role.Code.REVIEWER: Role.objects.create_reviewer,
        Role.Code.READ_ONLY: Role.objects.create_read_only,
    }[role_code]()
    username = f"tracking-{role_code}-{suffix or organization.slug}"
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return client


def _body(context):
    return {
        "destination": "https://example.com/landing",
        "utm_source": "LinkedIn",
        "utm_medium": "Social",
        "utm_campaign": "Launch",
        "campaign_id": str(context["campaign"].id),
        "platform_id": str(context["platform"].id),
        "product_id": str(context["product"].id),
        "published_post_id": str(context["published_post"].id),
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("role_code", "can_manage"),
    [
        (Role.Code.ADMINISTRATOR, True),
        (Role.Code.OPERATOR, True),
        (Role.Code.REVIEWER, False),
        (Role.Code.READ_ONLY, False),
    ],
)
def test_tracking_role_permissions_and_strict_create(tracking_context, role_code, can_manage):
    client = _client(tracking_context["organization"], role_code)
    assert client.get("/api/v1/tracking-links").status_code == 200
    response = client.post(
        "/api/v1/tracking-links", _body(tracking_context), format="json",
        HTTP_IDEMPOTENCY_KEY=f"role-{role_code}",
    )
    assert response.status_code == (201 if can_manage else 403)
    unknown = client.post(
        "/api/v1/tracking-links", {**_body(tracking_context), "raw_ip": "1.2.3.4"},
        format="json", HTTP_IDEMPOTENCY_KEY=f"unknown-{role_code}",
    )
    assert unknown.status_code in ({400} if can_manage else {403})


@pytest.mark.django_db
def test_tracking_and_short_api_idempotency_cursor_and_isolated_detail(tracking_context):
    client = _client(tracking_context["organization"], Role.Code.OPERATOR)
    assert client.post("/api/v1/tracking-links", _body(tracking_context), format="json").status_code == 400
    tracking_response = client.post(
        "/api/v1/tracking-links", _body(tracking_context), format="json",
        HTTP_IDEMPOTENCY_KEY="api-tracking",
    )
    assert tracking_response.status_code == 201
    tracking_id = tracking_response.json()["id"]
    assert client.get(f"/api/v1/tracking-links/{tracking_id}").status_code == 200
    listed = client.get("/api/v1/tracking-links?page_size=1").json()
    assert set(listed) == {"next", "previous", "results"}

    short_response = client.post(
        "/api/v1/short-links", {"tracking_link_id": tracking_id}, format="json",
        HTTP_IDEMPOTENCY_KEY="api-short",
    )
    assert short_response.status_code == 201
    short_id = short_response.json()["id"]
    assert client.get(f"/api/v1/short-links/{short_id}").status_code == 200
    assert client.post(
        "/api/v1/short-links", {"tracking_link_id": tracking_id, "unknown": 1}, format="json",
        HTTP_IDEMPOTENCY_KEY="api-short-unknown",
    ).status_code == 400


@pytest.mark.django_db
def test_channel_summary_is_database_aggregate_with_all_dimensions_and_filters(
    tracking_context, settings
):
    tracking = create_tracking_link(
        organization=tracking_context["organization"], destination="https://example.com/landing",
        utm_source="LinkedIn", utm_medium="Social", utm_campaign="Launch",
        campaign=tracking_context["campaign"], platform=tracking_context["platform"],
        product=tracking_context["product"], published_post=tracking_context["published_post"],
        idempotency_key="analytics-tracking",
    )
    short = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="analytics-short",
    )
    settings.TRACKING_TRUSTED_PROXY_CIDRS = ["10.0.0.0/8"]
    now = timezone.now()
    for offset, country in [(0, "DE"), (0, "DE"), (1, "US")]:
        record_click_event(
            short_link=short,
            occurred_at=now - timedelta(days=offset),
            meta={
                "REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "203.0.113.8",
                "HTTP_X_COUNTRY_CODE": country, "HTTP_USER_AGENT": "Test Browser",
            },
        )
    client = _client(tracking_context["organization"], Role.Code.READ_ONLY, suffix="analytics")
    start = (now - timedelta(days=2)).date().isoformat()
    end = now.date().isoformat()
    response = client.get(
        "/api/v1/analytics/channel-summary",
        {"start": start, "end": end, "country": "DE", "page_size": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    row = payload["results"][0]
    assert row == {
        "date": now.date().isoformat(),
        "campaign_id": str(tracking_context["campaign"].id),
        "platform_id": str(tracking_context["platform"].id),
        "country": "DE",
        "product_id": str(tracking_context["product"].id),
        "clicks": 2,
    }
    assert "network_hash" not in str(payload)
    for name, value in {
        "campaign": tracking_context["campaign"].id,
        "platform": tracking_context["platform"].id,
        "product": tracking_context["product"].id,
    }.items():
        filtered = client.get(
            "/api/v1/analytics/channel-summary",
            {"start": start, "end": end, name: str(value), "page_size": 10},
        )
        assert filtered.status_code == 200
        assert filtered.json()["count"] == 2


@pytest.mark.django_db
def test_channel_summary_rejects_unknown_repeated_and_oversized_ranges(tracking_context):
    client = _client(tracking_context["organization"], Role.Code.REVIEWER)
    assert client.get(
        "/api/v1/analytics/channel-summary?start=2026-01-01&start=2026-01-02&end=2026-01-03"
    ).status_code == 400
    assert client.get(
        "/api/v1/analytics/channel-summary",
        {"start": "2025-01-01", "end": "2026-12-31"},
    ).status_code == 400
    assert client.get(
        "/api/v1/analytics/channel-summary",
        {"start": "2026-01-01", "end": "2026-01-02", "raw": "true"},
    ).status_code == 400


@pytest.mark.django_db
def test_openapi_documents_tracking_contract_without_raw_privacy_fields(client):
    schema = client.get("/api/v1/schema").json()
    assert "/api/v1/tracking-links" in schema["paths"]
    assert "/api/v1/short-links" in schema["paths"]
    assert "/api/v1/analytics/channel-summary" in schema["paths"]
    assert "/r/{code}" in schema["paths"]
    parameters = schema["paths"]["/api/v1/tracking-links"]["post"]["parameters"]
    assert any(item["name"] == "Idempotency-Key" and item["required"] for item in parameters)
    assert not {"ip", "user_agent", "network_hash", "referrer"} & set(schema["components"]["schemas"])
