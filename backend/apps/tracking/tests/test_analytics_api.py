from datetime import timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.content.models import MasterContent, PlatformContent, content_writes
from apps.identity.models import Membership, Organization, Role
from apps.platforms.models import SocialAccount
from apps.publishing.models import PublishAttempt, PublishTask, publishing_writes
from apps.tracking.models import ShortLink, TrackingLink, tracking_writes
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
def test_tracking_create_maps_domain_validation_to_json_400(tracking_context):
    client = _client(tracking_context["organization"], Role.Code.OPERATOR, suffix="invalid-url")
    response = client.post(
        "/api/v1/tracking-links",
        {**_body(tracking_context), "destination": "https://example.com/%00hidden"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="invalid-encoded-url",
    )
    assert response.status_code == 400
    assert response.headers["Content-Type"].startswith("application/json")
    assert set(response.json()) == {"errors"}


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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "corruption",
    [
        "tracking", "short", "publishing", "short_code", "short_identity",
        "attempt_outcome", "attempt_error", "attempt_retry",
        "task_claim", "task_error", "task_retry", "task_cancel",
        "task_attempt_number", "task_content_version", "account_organization",
        "content_provenance", "master_content_provenance",
    ],
)
def test_channel_summary_excludes_corrupt_attribution_provenance(
    tracking_context, corruption
):
    tracking = create_tracking_link(
        organization=tracking_context["organization"], destination="https://example.com/analytics",
        utm_source="linkedin", utm_medium="social", utm_campaign="launch",
        campaign=tracking_context["campaign"], platform=tracking_context["platform"],
        product=tracking_context["product"], published_post=tracking_context["published_post"],
        idempotency_key=f"corrupt-tracking-{corruption}",
    )
    short = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key=f"corrupt-short-{corruption}",
    )
    now = timezone.now()
    record_click_event(
        short_link=short, occurred_at=now, meta={"REMOTE_ADDR": "198.51.100.8"}
    )
    if corruption == "tracking":
        with tracking_writes():
            TrackingLink.objects.filter(pk=tracking.pk).update(request_fingerprint="f" * 64)
    elif corruption == "short":
        with tracking_writes():
            ShortLink.objects.filter(pk=short.pk).update(request_fingerprint="f" * 64)
    elif corruption == "short_code":
        with tracking_writes():
            ShortLink.objects.filter(pk=short.pk).update(code="arbitrary-code")
    elif corruption == "short_identity":
        replacement = create_short_link(
            organization=tracking_context["organization"], tracking_link=tracking,
            idempotency_key="replacement-short-identity",
        )
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE tracking_clickevent SET short_link_id = %s WHERE short_link_id = %s",
                [replacement.id.hex, short.id.hex],
            )
    elif corruption == "publishing":
        with publishing_writes():
            PublishTask.objects.filter(pk=tracking_context["published_post"].task_id).update(
                request_fingerprint="f" * 64
            )
    elif corruption.startswith("attempt_"):
        changes = {
            "attempt_outcome": {"outcome": ""},
            "attempt_error": {"error": {"code": "CORRUPT"}},
            "attempt_retry": {"retry_at": now},
        }[corruption]
        with publishing_writes():
            PublishAttempt.objects.filter(
                pk=tracking_context["published_post"].attempt_id
            ).update(**changes)
    elif corruption.startswith("task_"):
        changes = {
            "task_claim": {"claim_token": uuid.uuid4()},
            "task_error": {"last_error": {"code": "CORRUPT"}},
            "task_retry": {"retry_not_before": now},
            "task_cancel": {"canceled_at": now},
            "task_attempt_number": {"attempt_number": 2},
            "task_content_version": {
                "content_version": tracking_context["content"].version + 1
            },
        }[corruption]
        with publishing_writes():
            PublishTask.objects.filter(
                pk=tracking_context["published_post"].task_id
            ).update(**changes)
    elif corruption == "account_organization":
        other = Organization.objects.create(name="Other", slug=f"other-{short.id.hex}")
        SocialAccount.objects.filter(pk=tracking_context["account"].pk).update(
            organization=other
        )
    elif corruption == "content_provenance":
        with content_writes():
            PlatformContent.objects.filter(pk=tracking_context["content"].pk).update(
                provenance={"corrupt": True}
            )
    else:
        with content_writes():
            MasterContent.objects.filter(
                pk=tracking_context["content"].master_content_id
            ).update(provenance={"corrupt": True})
    client = _client(
        tracking_context["organization"], Role.Code.READ_ONLY, suffix=f"corrupt-{corruption}"
    )
    response = client.get(
        "/api/v1/analytics/channel-summary",
        {"start": now.date().isoformat(), "end": now.date().isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0
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
