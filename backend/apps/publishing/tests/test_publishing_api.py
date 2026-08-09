from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.publishing.services import create_publish_task
from apps.publishing.services import execute_publish_task
from apps.publishing.models import PublishAttempt, publishing_writes


def _client(organization, role_code, suffix=""):
    role = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator,
        Role.Code.OPERATOR: Role.objects.create_operator,
        Role.Code.REVIEWER: Role.objects.create_reviewer,
        Role.Code.READ_ONLY: Role.objects.create_read_only,
    }[role_code]()
    username = f"publishing-{role_code}-{suffix or organization.slug}"
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return client


@pytest.mark.parametrize(
    ("role_code", "can_manage"),
    [
        (Role.Code.ADMINISTRATOR, True),
        (Role.Code.OPERATOR, True),
        (Role.Code.REVIEWER, False),
        (Role.Code.READ_ONLY, False),
    ],
)
def test_publish_task_role_permissions(publishing_context, role_code, can_manage):
    context = publishing_context
    client = _client(context["organization"], role_code)
    response = client.post(
        "/api/v1/publish-tasks",
        {
            "platform_content_id": str(context["content"].id),
            "social_account_id": str(context["account"].id),
            "timezone": "UTC",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=f"role-{role_code}",
    )

    assert client.get("/api/v1/publish-tasks").status_code == 200
    assert response.status_code == (201 if can_manage else 403)
    if can_manage:
        assert "credential" not in response.json()
        assert "connector_metadata" not in response.json()


def test_publish_create_requires_header_and_strict_endpoint_body(publishing_context):
    context = publishing_context
    client = _client(context["organization"], Role.Code.OPERATOR)
    body = {
        "platform_content_id": str(context["content"].id),
        "social_account_id": str(context["account"].id),
        "timezone": "UTC",
    }

    assert client.post("/api/v1/publish-tasks", body, format="json").status_code == 400
    assert client.post(
        "/api/v1/publish-tasks", {**body, "unknown": True}, format="json",
        HTTP_IDEMPOTENCY_KEY="unknown",
    ).status_code == 400
    assert client.post(
        "/api/v1/publish-tasks", {**body, "timezone": "Mars/Olympus"}, format="json",
        HTTP_IDEMPOTENCY_KEY="timezone",
    ).status_code == 400
    assert client.post(
        "/api/v1/publish-tasks", body, format="json",
        HTTP_IDEMPOTENCY_KEY="x" * 129,
    ).status_code == 400


def test_publish_and_calendar_datetimes_require_explicit_timezone(publishing_context):
    context = publishing_context
    client = _client(context["organization"], Role.Code.OPERATOR, suffix="aware")
    body = {
        "platform_content_id": str(context["content"].id),
        "social_account_id": str(context["account"].id),
        "scheduled_at": "2026-12-01T12:00:00",
        "timezone": "UTC",
    }

    response = client.post(
        "/api/v1/publish-tasks", body, format="json",
        HTTP_IDEMPOTENCY_KEY="naive-api",
    )
    assert response.status_code == 400
    assert client.get(
        "/api/v1/publish-calendar",
        {
            "start": "2026-12-01T00:00:00",
            "end": "2026-12-02T00:00:00Z",
            "timezone": "UTC",
        },
    ).status_code == 400


def test_publish_task_cross_organization_detail_and_action_are_404(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="isolated", scheduled_at=timezone.now() + timedelta(hours=1),
        actor=context["actor"],
    )
    other = Organization.objects.create(name="Other", slug="publishing-other")
    client = _client(other, Role.Code.ADMINISTRATOR)

    assert client.get(f"/api/v1/publish-tasks/{task.id}").status_code == 404
    assert client.post(
        f"/api/v1/publish-tasks/{task.id}/cancel", {}, format="json"
    ).status_code == 404


def test_calendar_groups_by_iana_local_date_and_applies_every_filter(
    publishing_context,
):
    context = publishing_context
    first_at = datetime(2026, 10, 24, 22, 30, tzinfo=dt_timezone.utc)
    second_at = datetime(2026, 10, 25, 23, 30, tzinfo=dt_timezone.utc)
    first = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="dst-first", scheduled_at=first_at,
        timezone_name="Europe/Berlin", actor=context["actor"],
    )
    second = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="dst-second", scheduled_at=second_at,
        timezone_name="Europe/Berlin", actor=context["actor"],
    )
    client = _client(context["organization"], Role.Code.READ_ONLY)
    query = (
        "?start=2026-10-24T00:00:00Z&end=2026-10-27T00:00:00Z"
        "&timezone=Europe/Berlin"
        f"&platform={context['platform'].id}&account={context['account'].id}"
        f"&product={context['product'].id}&campaign={context['campaign'].id}"
        "&country=DE&status=SCHEDULED"
    )

    response = client.get(f"/api/v1/publish-calendar{query}")

    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/Berlin"
    assert [day["date"] for day in response.json()["days"]] == [
        "2026-10-25", "2026-10-26",
    ]
    ids = [entry["id"] for day in response.json()["days"] for entry in day["entries"]]
    assert ids == [str(first.id), str(second.id)]
    assert response.json()["days"][0]["entries"][0]["scheduled_at"].endswith("Z")


def test_publish_calendar_query_count_does_not_scale_with_rows(publishing_context):
    context = publishing_context
    base = timezone.now() + timedelta(days=1)
    create_publish_task(
        content=context["content"], account=context["account"], idempotency_key="one",
        scheduled_at=base, actor=context["actor"],
    )
    client = _client(context["organization"], Role.Code.READ_ONLY)
    start = (base - timedelta(hours=1)).isoformat()
    end = (base + timedelta(days=2)).isoformat()
    params = {"start": start, "end": end, "timezone": "UTC"}
    with CaptureQueriesContext(connection) as single:
        assert client.get("/api/v1/publish-calendar", params).status_code == 200
    for index in range(5):
        create_publish_task(
            content=context["content"], account=context["account"],
            idempotency_key=f"many-{index}", scheduled_at=base + timedelta(minutes=index + 1),
            actor=context["actor"],
        )
    with CaptureQueriesContext(connection) as many:
        assert client.get("/api/v1/publish-calendar", params).status_code == 200
    assert len(many) == len(single)


def test_publishing_openapi_documents_header_actions_and_calendar(publishing_context):
    client = _client(publishing_context["organization"], Role.Code.READ_ONLY)
    schema = client.get("/api/v1/schema").json()

    create = schema["paths"]["/api/v1/publish-tasks"]["post"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in create["parameters"])
    assert "post" in schema["paths"]["/api/v1/publish-tasks/{task_id}/cancel"]
    assert "post" in schema["paths"]["/api/v1/publish-tasks/{task_id}/retry"]
    assert "get" in schema["paths"]["/api/v1/publish-calendar"]


def test_corrupt_attempt_history_is_omitted_and_detail_action_are_404(
    publishing_context,
):
    context = publishing_context
    task = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="corrupt-attempt", actor=context["actor"],
    )
    execute_publish_task(task.id)
    with publishing_writes():
        PublishAttempt.objects.filter(task=task).update(
            error={"code": "FORGED", "secret": "must-not-leak"}
        )
    client = _client(context["organization"], Role.Code.ADMINISTRATOR)

    assert client.get(f"/api/v1/publish-tasks/{task.id}").status_code == 404
    assert client.post(
        f"/api/v1/publish-tasks/{task.id}/cancel", {}, format="json"
    ).status_code == 404
    response = client.get("/api/v1/publish-tasks")
    assert response.status_code == 200
    assert str(task.id) not in response.content.decode()
    assert "must-not-leak" not in response.content.decode()
