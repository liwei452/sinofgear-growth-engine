import importlib

import pytest
from django.apps import apps as django_apps
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.identity.models import Role
from apps.jobs.models import Job
from apps.jobs.services import JobService

from .conftest import member_client


def _job(organization, suffix):
    return JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": suffix, "api_key": "must-not-leak"},
    )


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
def test_job_permissions_and_safe_response(
    api_organizations, api_roles, role_code, can_manage
):
    own, _ = api_organizations
    job = _job(own, role_code)
    _, client = member_client(
        organization=own, role=api_roles[role_code], username=f"jobs-{role_code}"
    )

    detail = client.get(f"/api/v1/jobs/{job.id}")
    cancel = client.post(f"/api/v1/jobs/{job.id}/cancel", {}, format="json")

    assert detail.status_code == 200
    assert set(detail.json()) == {
        "job_id", "type", "status", "progress", "attempt", "max_attempts",
        "created_at", "finished_at", "error", "result_reference",
        "generation_mode", "generation_label",
    }
    assert detail.json()["generation_mode"] == "NOT_STARTED"
    assert detail.json()["generation_label"] == "尚未启动生成服务"
    assert "must-not-leak" not in str(detail.json())
    assert cancel.status_code == (200 if can_manage else 403)


@pytest.mark.django_db
def test_jobs_are_organization_isolated_as_404(api_organizations, api_roles):
    own, other = api_organizations
    foreign = _job(other, "foreign")
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.ADMINISTRATOR],
        username="jobs-isolated",
    )

    assert client.get(f"/api/v1/jobs/{foreign.id}").status_code == 404
    assert client.post(f"/api/v1/jobs/{foreign.id}/cancel", {}, format="json").status_code == 404


@pytest.mark.django_db
def test_job_list_filters_paginates_and_rejects_invalid_values(api_organizations, api_roles):
    own, _ = api_organizations
    jobs = [_job(own, f"page-{index}") for index in range(3)]
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-list",
    )

    response = client.get("/api/v1/jobs", {"page_size": 2, "status": "QUEUED"})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert response.json()["next"] is not None
    assert client.get("/api/v1/jobs", {"status": "NOPE"}).status_code == 400
    assert client.get("/api/v1/jobs", {"type": "NOPE"}).status_code == 400
    assert client.get("/api/v1/jobs", {"job_id": "not-a-uuid"}).status_code == 400
    assert client.get("/api/v1/jobs?status=QUEUED&status=FAILED").status_code == 400
    assert {str(item.id) for item in jobs} >= {
        item["job_id"] for item in response.json()["results"]
    }


@pytest.mark.django_db
def test_retry_cancel_bodies_are_strict_and_lifecycle_errors_are_json(
    api_organizations, api_roles
):
    own, _ = api_organizations
    job = _job(own, "strict")
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.OPERATOR],
        username="jobs-actions",
    )

    unknown = client.post(
        f"/api/v1/jobs/{job.id}/cancel", {"unexpected": True}, format="json"
    )
    invalid_retry = client.post(f"/api/v1/jobs/{job.id}/retry", {}, format="json")

    assert unknown.status_code == 400
    assert unknown.json() == {
        "errors": {"unexpected": ["Unknown field."]},
        "code": "http_400",
        "message": "The request contains invalid fields.",
        "recovery_action": "Correct the request and try again.",
    }
    assert invalid_retry.status_code == 409
    assert set(invalid_retry.json()) == {"code", "detail", "message", "recovery_action"}


@pytest.mark.django_db
def test_job_list_query_count_is_bounded(api_organizations, api_roles):
    own, _ = api_organizations
    for index in range(12):
        _job(own, f"query-{index}")
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-query-count",
    )

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert len(queries) <= 7


@pytest.mark.django_db
def test_jobs_openapi_contract(api_organizations, api_roles):
    own, _ = api_organizations
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-schema",
    )
    schema = client.get("/api/v1/schema").json()

    assert {"get"} <= set(schema["paths"]["/api/v1/jobs"])
    assert "get" in schema["paths"]["/api/v1/jobs/{job_id}"]
    assert "post" in schema["paths"]["/api/v1/jobs/{job_id}/retry"]
    assert "post" in schema["paths"]["/api/v1/jobs/{job_id}/cancel"]


@pytest.mark.django_db
def test_job_permission_migration_merges_and_preserves_custom_roles(api_roles):
    custom = Role.objects.create(
        code="CUSTOM_JOBS", name="Custom", permissions=["custom.permission"]
    )
    operator = api_roles[Role.Code.OPERATOR]
    operator.permissions = ["legacy.custom", "products.read"]
    operator.save(update_fields=["permissions"])
    migration = importlib.import_module(
        "apps.identity.migrations.0006_refresh_job_permissions"
    )

    migration.refresh_job_permissions(django_apps, None)

    operator.refresh_from_db()
    custom.refresh_from_db()
    assert operator.permissions == [
        "legacy.custom", "products.read", "jobs.read", "jobs.manage"
    ]
    assert custom.permissions == ["custom.permission"]
