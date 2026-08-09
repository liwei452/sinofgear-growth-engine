from datetime import datetime, timedelta, timezone as dt_timezone
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.publishing.services import (
    cancel_publish_task, claim_publish_task, create_publish_task,
    execute_publish_task, retry_publish_task,
)
from apps.publishing.models import (
    PublishAttempt, PublishedPost, PublishTask, publishing_writes,
)


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


def test_publish_calendar_has_deterministic_entry_bound_and_metadata(
    publishing_context,
):
    context = publishing_context
    base = timezone.now() + timedelta(days=1)
    tasks = [
        create_publish_task(
            content=context["content"], account=context["account"],
            idempotency_key=f"calendar-bound-{index}",
            scheduled_at=base + timedelta(seconds=index), actor=context["actor"],
        )
        for index in range(201)
    ]
    client = _client(
        context["organization"], Role.Code.READ_ONLY, suffix="calendar-bound"
    )

    response = client.get(
        "/api/v1/publish-calendar",
        {
            "start": (base - timedelta(minutes=1)).isoformat(),
            "end": (base + timedelta(days=1)).isoformat(),
            "timezone": "UTC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    entries = [entry for day in body["days"] for entry in day["entries"]]
    assert [entry["id"] for entry in entries] == [str(task.id) for task in tasks[:200]]
    assert body["metadata"] == {
        "max_entries": 200,
        "returned_entries": 200,
        "truncated": True,
    }


def test_publishing_openapi_documents_header_actions_and_calendar(publishing_context):
    client = _client(publishing_context["organization"], Role.Code.READ_ONLY)
    schema = client.get("/api/v1/schema").json()

    create = schema["paths"]["/api/v1/publish-tasks"]["post"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in create["parameters"])
    assert "post" in schema["paths"]["/api/v1/publish-tasks/{task_id}/cancel"]
    assert "post" in schema["paths"]["/api/v1/publish-tasks/{task_id}/retry"]
    assert "get" in schema["paths"]["/api/v1/publish-calendar"]
    assert set(schema["paths"]["/api/v1/publish-tasks/schedule"]) == {"post"}


def test_publishing_openapi_matches_runtime_envelopes_and_attempt_bound(
    publishing_context,
):
    client = _client(
        publishing_context["organization"], Role.Code.READ_ONLY,
        suffix="schema-envelope",
    )
    schema = client.get("/api/v1/schema").json()
    list_schema = schema["paths"]["/api/v1/publish-tasks"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    calendar_schema = schema["paths"]["/api/v1/publish-calendar"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    if "$ref" in list_schema:
        list_schema = schema["components"]["schemas"][
            list_schema["$ref"].rsplit("/", 1)[-1]
        ]
    if "$ref" in calendar_schema:
        calendar_schema = schema["components"]["schemas"][
            calendar_schema["$ref"].rsplit("/", 1)[-1]
        ]

    assert set(list_schema["properties"]) == {"next", "previous", "results"}
    assert list_schema["properties"]["results"]["type"] == "array"
    assert set(calendar_schema["properties"]) == {
        "timezone", "start", "end", "metadata", "days",
    }
    metadata = calendar_schema["properties"]["metadata"]
    if "$ref" in metadata:
        metadata = schema["components"]["schemas"][metadata["$ref"].rsplit("/", 1)[-1]]
    assert set(metadata["properties"]) == {
        "max_entries", "returned_entries", "truncated",
    }
    task_schema = schema["components"]["schemas"]["PublishTask"]
    assert task_schema["properties"]["attempts"]["maxItems"] == 10


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


@pytest.mark.parametrize(
    "corruption",
    [
        "scheduled_started", "queued_error", "running_claim", "failed_error",
        "failed_retry", "attempt_chronology", "succeeded_external",
        "succeeded_time", "canceled_started",
    ],
)
def test_exact_state_matrix_omits_mismatched_rows_and_safe_errors(
    publishing_context, corruption,
):
    context = publishing_context
    scheduled_at = (
        timezone.now() + timedelta(hours=1)
        if corruption == "scheduled_started" else None
    )
    if corruption == "failed_retry":
        context["account"].connector_metadata = {"mock_outcome": "rate_limit"}
        context["account"].save(update_fields=["connector_metadata", "updated_at"])
    elif corruption in {"failed_error", "attempt_chronology"}:
        context["account"].connector_metadata = {"mock_outcome": "provider_error"}
        context["account"].save(update_fields=["connector_metadata", "updated_at"])
    task = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key=f"matrix-{corruption}", scheduled_at=scheduled_at,
        actor=context["actor"],
    )
    if corruption == "running_claim":
        claim_publish_task(task.id)
    elif corruption in {
        "failed_error", "failed_retry", "attempt_chronology",
        "succeeded_external", "succeeded_time",
    }:
        execute_publish_task(task.id)
        if corruption == "attempt_chronology":
            task.refresh_from_db()
            retry_publish_task(task, actor=context["actor"])
            execute_publish_task(task.id)
    elif corruption == "canceled_started":
        cancel_publish_task(task, actor=context["actor"])

    with publishing_writes():
        if corruption == "scheduled_started":
            PublishTask.objects.filter(pk=task.pk).update(started_at=timezone.now())
        elif corruption == "queued_error":
            PublishTask.objects.filter(pk=task.pk).update(
                last_error={"code": "PROVIDER_ERROR", "message": "must-not-leak"}
            )
        elif corruption == "running_claim":
            PublishAttempt.objects.filter(task=task).update(claim_token=uuid.uuid4())
        elif corruption == "failed_error":
            PublishTask.objects.filter(pk=task.pk).update(
                last_error={
                    "code": "PROVIDER_ERROR", "message": "wrong",
                    "secret": "must-not-leak",
                }
            )
        elif corruption == "failed_retry":
            PublishTask.objects.filter(pk=task.pk).update(
                retry_not_before=timezone.now() + timedelta(minutes=5)
            )
        elif corruption == "attempt_chronology":
            attempts = list(PublishAttempt.objects.filter(task=task).order_by("number"))
            PublishAttempt.objects.filter(pk=attempts[0].pk).update(
                finished_at=attempts[1].started_at + timedelta(seconds=1)
            )
        elif corruption == "succeeded_external":
            PublishedPost.objects.filter(task=task).update(external_id="forged")
        elif corruption == "succeeded_time":
            post = PublishedPost.objects.get(task=task)
            PublishedPost.objects.filter(pk=post.pk).update(
                published_at=post.published_at + timedelta(seconds=1)
            )
        else:
            PublishTask.objects.filter(pk=task.pk).update(started_at=timezone.now())

    client = _client(
        context["organization"], Role.Code.ADMINISTRATOR, suffix=corruption
    )
    assert client.get(f"/api/v1/publish-tasks/{task.id}").status_code == 404
    response = client.get("/api/v1/publish-tasks")
    assert response.status_code == 200
    assert str(task.id) not in response.content.decode()
    assert "must-not-leak" not in response.content.decode()
