from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService


def member_client(organization, role, username):
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return user, client


def make_run(organization, *, suffix, status=AIRun.Status.SUCCEEDED, secrets=False):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief": suffix},
        idempotency_key=f"ai-api-{suffix}",
    )
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE", code=f"prompt-{suffix}", provider="fake",
        model="fake-v1", template="SECRET TEMPLATE {product_name}",
        output_schema={"type": "object"}, status=PromptVersion.Status.PUBLISHED,
    )
    now = timezone.now()
    with ai_audit_writes():
        return AIRun.objects.create(
            organization=organization, job=job, job_attempt=1, prompt_version=prompt,
            provider="fake", model="fake-v1", status=status, confidence="0.8750",
            input_snapshot={"safe": "input", "Authorization": "Bearer secret"} if secrets else {"safe": suffix},
            output_json={"title": suffix, "nested": {"api_key": "secret"}} if secrets else {"title": suffix},
            provider_metadata={"request_id": suffix, "token": "secret"},
            error={"message": "safe", "password": "secret"} if secrets else None,
            human_correction={"body": "edited", "client_secret": "secret"} if secrets else None,
            started_at=now - timedelta(seconds=2), finished_at=now,
        )


@pytest.fixture
def ai_api(db):
    own = Organization.objects.create(name="AI API Own", slug="ai-api-own")
    other = Organization.objects.create(name="AI API Other", slug="ai-api-other")
    role = Role.objects.create_read_only()
    user, client = member_client(own, role, "ai-api-reader")
    return own, other, user, client


@pytest.mark.django_db
def test_ai_run_detail_is_organization_scoped_and_recursively_scrubbed(ai_api):
    own, other, _user, client = ai_api
    run = make_run(own, suffix="safe", secrets=True)
    foreign = make_run(other, suffix="foreign")

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "id", "job_id", "job_attempt", "status", "prompt", "provider", "model",
        "confidence", "human_correction", "reviewer", "created_at", "started_at",
        "finished_at", "reviewed_at", "input_snapshot", "output_json", "error",
        "provider_metadata",
    }
    assert data["prompt"] == {
        "purpose": "CONTENT_GENERATE", "code": "prompt-safe", "version": 1,
        "provider": "fake", "model": "fake-v1",
    }
    serialized = str(data).casefold()
    for secret in ("bearer secret", "api_key", "password", "client_secret", "secret template"):
        assert secret not in serialized
    assert client.get(f"/api/v1/ai-runs/{foreign.id}").status_code == 404


@pytest.mark.django_db
def test_ai_run_list_filters_paginates_and_rejects_bad_queries(ai_api):
    own, _other, _user, client = ai_api
    first = make_run(own, suffix="one", status=AIRun.Status.RUNNING)
    second = make_run(own, suffix="two", status=AIRun.Status.SUCCEEDED)
    make_run(own, suffix="three", status=AIRun.Status.SUCCEEDED)

    page = client.get("/api/v1/ai-runs", {"page_size": 1, "status": "SUCCEEDED"})
    assert page.status_code == 200
    assert len(page.json()["results"]) == 1
    assert page.json()["next"] is not None
    by_job = client.get("/api/v1/ai-runs", {"job": str(first.job_id)})
    assert [item["id"] for item in by_job.json()["results"]] == [str(first.id)]
    assert str(second.id) in {
        item["id"] for item in client.get("/api/v1/ai-runs", {"status": "SUCCEEDED"}).json()["results"]
    }
    assert client.get("/api/v1/ai-runs", {"status": "NOPE"}).status_code == 400
    assert client.get("/api/v1/ai-runs", {"job": "bad"}).status_code == 400
    assert client.get("/api/v1/ai-runs?status=RUNNING&status=FAILED").status_code == 400
    assert client.get("/api/v1/ai-runs", {"unknown": "x"}).status_code == 400
    assert client.get("/api/v1/ai-runs", {"cursor": "not-a-cursor"}).status_code == 400
    assert client.get("/api/v1/ai-runs", {"page_size": 51}).status_code == 400


@pytest.mark.django_db
def test_ai_run_api_requires_jobs_read_and_is_in_openapi(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="schema")
    custom = Role.objects.create(code="NO_AI_AUDIT", name="No audit", permissions=[])
    _blocked_user, blocked = member_client(own, custom, "ai-api-blocked")

    assert blocked.get("/api/v1/ai-runs").status_code == 403
    assert blocked.get(f"/api/v1/ai-runs/{run.id}").status_code == 403
    schema = client.get("/api/v1/schema").json()
    assert "get" in schema["paths"]["/api/v1/ai-runs"]
    assert "get" in schema["paths"]["/api/v1/ai-runs/{run_id}"]
