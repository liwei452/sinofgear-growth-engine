import importlib

import pytest
from datetime import timedelta
from uuid import uuid4
from django.apps import apps as django_apps
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.identity.models import Role
from apps.jobs.models import Job, job_service_writes
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
        "created_at", "finished_at", "error", "result_reference", "source_reference",
        "retry_count", "next_retry_at",
    }
    assert "must-not-leak" not in str(detail.json())
    assert cancel.status_code == (200 if can_manage else 403)


@pytest.mark.django_db
def test_job_error_is_allowlisted_at_public_boundary(api_organizations, api_roles):
    own, _ = api_organizations
    job = _job(own, "safe-public-error")
    with job_service_writes():
        Job.objects.filter(pk=job.id).update(
            status=Job.Status.FAILED,
            error={
                "code": "provider_balance_required",
                "message": "upstream body sk-secret-must-not-leak",
                "recovery_action": "raw provider recovery",
                "provider_body": {"reasoning_content": "private chain"},
            },
        )
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-safe-public-error",
    )

    payload = client.get(f"/api/v1/jobs/{job.id}").json()

    assert payload["error"] == {
        "code": "provider_balance_required",
        "message": "AI provider balance is insufficient.",
        "recovery": "Ask an administrator to add balance, then try again.",
    }
    assert "sk-secret-must-not-leak" not in str(payload)
    assert "reasoning_content" not in str(payload)


@pytest.mark.django_db
def test_job_retry_progress_exposes_only_count_and_due_time(api_organizations, api_roles):
    own, _ = api_organizations
    job = _job(own, "safe-retry")
    due = timezone.now() + timedelta(minutes=2)
    with ai_audit_writes():
        prompt = PromptVersion.objects.create(
            purpose="CONTENT_GENERATE", code="job-public-retry", provider="deepseek",
            model="private-model-name", template="prompt", output_schema={"type": "object"},
            version=1, status=PromptVersion.Status.PUBLISHED,
        )
        AIRun.objects.create(
            organization=own, job=job, job_attempt=1, prompt_version=prompt,
            provider="deepseek", model="private-model-name", input_snapshot={},
            status=AIRun.Status.RUNNING, started_at=timezone.now(),
            transport_retry_count=1, next_retry_at=due,
            provider_metadata={"provider_body": "secret"},
        )
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-safe-retry",
    )

    payload = client.get(f"/api/v1/jobs/{job.id}").json()

    assert payload["retry_count"] == 1
    assert payload["next_retry_at"] == due.isoformat().replace("+00:00", "Z")
    assert "private-model-name" not in str(payload)
    assert "provider_body" not in str(payload)


@pytest.mark.django_db
def test_content_job_list_and_detail_return_only_a_valid_brief_source_reference(
    api_organizations, api_roles,
):
    own, _ = api_organizations
    brief_id = uuid4()
    job = JobService.create(
        organization=own,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={
            "brief_id": str(brief_id), "brief_version": 3,
            "prompt": "must-not-leak", "customer_text": "must-not-leak",
        },
    )
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-source-reference",
    )

    detail = client.get(f"/api/v1/jobs/{job.id}").json()
    listed = next(
        item for item in client.get("/api/v1/jobs", {"job_id": job.id}).json()["results"]
        if item["job_id"] == str(job.id)
    )

    assert detail["source_reference"] == {
        "brief_id": str(brief_id), "brief_version": 3,
    }
    assert listed["source_reference"] == detail["source_reference"]
    assert "must-not-leak" not in str(detail)
    assert set(detail["source_reference"]) == {"brief_id", "brief_version"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"brief_id": "not-a-uuid", "brief_version": 1},
        {"brief_id": str(uuid4()), "brief_version": 0},
        {"brief_id": str(uuid4()), "brief_version": "2"},
        {"brief_id": str(uuid4()), "brief_version": True},
    ],
)
def test_content_job_malformed_source_reference_is_safely_null(
    api_organizations, api_roles, snapshot,
):
    own, _ = api_organizations
    job = JobService.create(
        organization=own,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={**snapshot, "case": str(uuid4())},
    )
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username=f"jobs-malformed-reference-{job.id}",
    )

    assert client.get(f"/api/v1/jobs/{job.id}").json()["source_reference"] is None


@pytest.mark.django_db
def test_non_content_job_never_exposes_a_source_reference(api_organizations, api_roles):
    own, _ = api_organizations
    job = JobService.create(
        organization=own,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"brief_id": str(uuid4()), "brief_version": 2},
    )
    _, client = member_client(
        organization=own,
        role=api_roles[Role.Code.READ_ONLY],
        username="jobs-non-content-reference",
    )

    assert client.get(f"/api/v1/jobs/{job.id}").json()["source_reference"] is None


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
    assert len(queries) <= 5


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
    source_reference = schema["components"]["schemas"]["Job"]["properties"]["source_reference"]
    assert source_reference["nullable"] is True
    reference_name = source_reference["allOf"][0]["$ref"].rsplit("/", 1)[-1]
    reference_schema = schema["components"]["schemas"][reference_name]
    assert set(reference_schema["properties"]) == {"brief_id", "brief_version"}
    assert reference_schema["properties"]["brief_id"]["format"] == "uuid"
    assert reference_schema["properties"]["brief_version"]["minimum"] == 1


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
