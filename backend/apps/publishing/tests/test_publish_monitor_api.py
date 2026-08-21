from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.publishing.serializers import PublishMonitorTaskSerializer
from apps.publishing.services import create_publish_task, publish_task_consistency_queryset

from .test_ui_safety_contract import _failed
from .test_publishing_api import _additional_account


def _client(organization, role_code, suffix):
    role = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator,
        Role.Code.READ_ONLY: Role.objects.create_read_only,
    }[role_code]()
    user = get_user_model().objects.create_user(
        username=f"monitor-{suffix}", password="password"
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


def test_monitor_aggregates_and_returns_server_side_safe_display_fields(
    publishing_context, monkeypatch,
):
    context = publishing_context
    failed = _failed(context, monkeypatch, suffix="monitor")
    waiting = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="monitor-waiting",
        scheduled_at=timezone.now() + timedelta(hours=2), actor=context["actor"],
    )
    client = _client(context["organization"], Role.Code.READ_ONLY, "summary")

    response = client.get("/api/v1/publish-tasks/monitor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "attention_count": 0,
        "provider_pending_count": 0,
        "failed_count": 1,
        "waiting_count": 1,
        "today_succeeded_count": 0,
    }
    assert [item["id"] for item in payload["results"]] == [str(failed.id), str(waiting.id)]
    item = payload["results"][0]
    assert item["platform_code"] == context["platform"].code
    assert item["platform_name"] == context["platform"].name
    assert item["social_account_display_name"] == context["account"].display_name
    assert item["content_title"] == "Generated"
    serialized = str(payload)
    assert "secret_reference" not in serialized
    assert "connector_metadata" not in serialized
    assert "request_fingerprint" not in serialized

    loaded = publish_task_consistency_queryset(context["organization"]).get(pk=failed.pk)
    loaded.platform_content.payload = {
        **loaded.platform_content.payload, "body": "Evidence " * 80,
    }
    excerpt = PublishMonitorTaskSerializer(loaded).data["content_excerpt"]
    assert len(excerpt) == 180
    assert excerpt.endswith("…")
    assert excerpt != "Evidence " * 80


def test_monitor_is_organization_scoped_and_requires_read_permission(
    publishing_context,
):
    context = publishing_context
    create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="monitor-isolated",
        scheduled_at=timezone.now() + timedelta(hours=2), actor=context["actor"],
    )
    other = Organization.objects.create(name="Monitor Other", slug="monitor-other")
    other_client = _client(other, Role.Code.READ_ONLY, "other")
    response = other_client.get(
        f"/api/v1/publish-tasks/monitor?organization_id={context['organization'].id}"
    )
    assert response.status_code == 400
    clean = other_client.get("/api/v1/publish-tasks/monitor")
    assert clean.status_code == 200
    assert clean.json()["results"] == []
    assert sum(clean.json()["summary"].values()) == 0

    anonymous = APIClient().get("/api/v1/publish-tasks/monitor")
    assert anonymous.status_code in {401, 403}


def test_monitor_group_filter_and_page_size_are_server_enforced(
    publishing_context, monkeypatch,
):
    context = publishing_context
    _failed(context, monkeypatch, suffix="filter")
    create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="monitor-filter-waiting",
        scheduled_at=timezone.now() + timedelta(hours=2), actor=context["actor"],
    )
    client = _client(context["organization"], Role.Code.READ_ONLY, "filter")

    response = client.get("/api/v1/publish-tasks/monitor?group=FAILED&page_size=1")

    assert response.status_code == 200
    assert [item["status"] for item in response.json()["results"]] == ["FAILED"]
    assert client.get("/api/v1/publish-tasks/monitor?page_size=51").status_code == 400
    assert client.get("/api/v1/publish-tasks/monitor?group=UNKNOWN").status_code == 400


def test_monitor_query_count_is_constant_for_bounded_results(
    publishing_context, django_assert_num_queries,
):
    context = publishing_context
    for index in range(4):
        account = context["account"] if index == 0 else _additional_account(context, index)
        create_publish_task(
            content=context["content"], account=account,
            idempotency_key=f"monitor-query-{index}",
            scheduled_at=timezone.now() + timedelta(hours=index + 1),
            actor=context["actor"],
        )
    client = _client(context["organization"], Role.Code.READ_ONLY, "queries")
    client.get("/api/v1/publish-tasks/monitor")

    with django_assert_num_queries(10):
        response = client.get("/api/v1/publish-tasks/monitor")
    assert response.status_code == 200
    assert len(response.json()["results"]) == 4
