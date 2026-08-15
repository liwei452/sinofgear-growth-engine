import json
from copy import deepcopy
from datetime import timedelta
from urllib.parse import quote, unquote

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import override_settings
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
        "purpose": "CONTENT_GENERATE", "code": "prompt-safe", "version": run.prompt_version.version,
        "provider": "fake", "model": "fake-v1",
    }
    serialized = str(data).casefold()
    for secret in ("bearer secret", "api_key", "password", "client_secret", "secret template"):
        assert secret not in serialized
    assert client.get(f"/api/v1/ai-runs/{foreign.id}").status_code == 404


@pytest.mark.django_db
def test_ai_run_nullable_json_fields_are_null_at_runtime(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="nullable")
    with ai_audit_writes():
        AIRun.objects.filter(pk=run.pk).update(output_json=None, human_correction=None)

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    assert response.json()["output_json"] is None
    assert response.json()["human_correction"] is None


@pytest.mark.django_db
@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_product_ai_status_is_safe_and_never_returns_key(ai_api, monkeypatch):
    _own, _other, _user, client = ai_api
    secret = "provider-secret-never-return"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)

    data = client.get("/api/v1/ai/provider-status").json()

    assert data == {
        "mode": "CONFIGURED_AI",
        "provider_label": "DeepSeek 官方 API",
        "model": "deepseek-chat",
        "configured": True,
        "real_requests_enabled": True,
    }
    assert secret not in str(data)


@pytest.mark.django_db
def test_ai_run_detail_is_allowlisted_value_redacted_bounded_and_non_mutating(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="bounded")
    stored = {
        "input_snapshot": {
            "brief_id": "brief-1",
            "target_country": "Germany",
            "keywords": ["precision", "Authorization Bearer TOP-SECRET"],
            "products": [{
                "name_en": "Gear",
                "detail": "api_key=KEY-SECRET",
                "deep": {"one": {"two": {"three": {"four": "password=PASS-SECRET"}}}},
            }],
            "unknown_private_blob": "must-not-be-public",
            "oversized": "x" * 20_000,
        },
        "output_json": {
            "title": "Safe title token=OUTPUT-SECRET",
            "body": "b" * 20_000,
            "cta": "Contact us",
            "concept_codes": [f"CODE-{index}" for index in range(100)],
            "internal": {"cookie": "COOKIE-SECRET"},
        },
        "provider_metadata": {
            "provider_code": "fake",
            "request_id": "cookie=REQUEST-SECRET",
            "raw_response": "must-not-be-public",
        },
        "error": {
            "code": "provider_error",
            "message": "Authorization: Bearer ERROR-SECRET",
            "detail": "password=ERROR-PASSWORD",
        },
        "human_correction": {
            "title": "Edited",
            "body": "token=HUMAN-SECRET",
            "cta": "Review",
            "concept_codes": ["SAFE"] * 50,
            "notes": "must-not-be-public",
        },
    }
    original = deepcopy(stored)
    with ai_audit_writes():
        AIRun.objects.filter(pk=run.pk).update(**stored)

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    for forbidden in (
        "top-secret", "key-secret", "pass-secret", "output-secret",
        "cookie-secret", "request-secret", "error-secret", "error-password",
        "human-secret", "must-not-be-public", "unknown_private_blob", "raw_response",
    ):
        assert forbidden not in serialized
    assert data["error"] == {
        "code": "provider_error", "message": "AI provider generation failed.",
    }
    assert data["provider_metadata"] == {"provider_code": "fake"}
    assert set(data["output_json"]) <= {"title", "body", "cta", "concept_codes", "platform_code", "_truncated"}
    assert set(data["human_correction"]) <= {"title", "body", "cta", "concept_codes", "platform_code", "_truncated"}
    assert "[TRUNCATED]" in serialized or '"_truncated": true' in serialized
    assert len(response.content) <= 32_768
    run.refresh_from_db()
    for field, value in original.items():
        assert getattr(run, field) == value


@pytest.mark.django_db
def test_ai_run_public_strings_fail_closed_for_credential_markers(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="fail-closed")
    basic_value = "QkFTSUMtU0VOVElORUwtMDE="
    sensitive_values = [
        f"Authorization： Basic {basic_value} trailing BASIC-SENTINEL-01",
        'authorization=\tBearer "BEARER-SENTINEL-02 has spaces"',
        "api_key = 'API-SENTINEL-03 continues here'",
        "accessToken: ACCESS-SENTINEL-04 with suffix",
        "refresh_token=REFRESH-SENTINEL-05 more",
        "client secret：CLIENT-SENTINEL-06 more",
        "password = PASSWORD-SENTINEL-07 more",
        "passPhrase: PASSPHRASE-SENTINEL-08 more",
        "cookie=COOKIE-SENTINEL-09; Path=/",
        "set-cookie： SETCOOKIE-SENTINEL-10; HttpOnly",
        "token=TOKEN-SENTINEL-11 and trailing words",
        "ＡＰＩ＿ＫＥＹ＝ＦＵＬＬＷＩＤＴＨ－ＳＥＮＴＩＮＥＬ－１２",
        "https://example.com/path?access_token=URL-SENTINEL-13#section",
        "https://example.com/#refreshToken=FRAGMENT-SENTINEL-14",
        "https://example.com/?client_secret=ENCODED%2DSENTINEL%2D15",
    ]
    stored = {
        "input_snapshot": {
            "brief_id": "brief-safe",
            "landing_page_url": sensitive_values[-3],
            "keywords": sensitive_values,
        },
        "output_json": {
            "title": sensitive_values[0],
            "body": sensitive_values[1],
            "cta": sensitive_values[2],
            "concept_codes": [*sensitive_values[3:], "token budget", "password policy"],
        },
        "human_correction": {
            "title": sensitive_values[4],
            "body": sensitive_values[5],
            "cta": "safe correction",
            "concept_codes": [sensitive_values[6]],
        },
    }
    original = deepcopy(stored)
    with ai_audit_writes():
        AIRun.objects.filter(pk=run.pk).update(**stored)

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    sentinels = [
        "basic-sentinel-01", "bearer-sentinel-02", "api-sentinel-03",
        "access-sentinel-04", "refresh-sentinel-05", "client-sentinel-06",
        "password-sentinel-07", "passphrase-sentinel-08", "cookie-sentinel-09",
        "setcookie-sentinel-10", "token-sentinel-11",
        "ｆｕｌｌｗｉｄｔｈ－ｓｅｎｔｉｎｅｌ－１２", "url-sentinel-13",
        "fragment-sentinel-14", "encoded-sentinel-15",
    ]
    for sentinel in sentinels:
        assert sentinel not in serialized
        assert quote(sentinel, safe="").casefold() not in serialized
    assert basic_value.casefold() not in serialized
    assert "token budget" in data["output_json"]["concept_codes"]
    assert "password policy" in data["output_json"]["concept_codes"]
    run.refresh_from_db()
    for field, value in original.items():
        assert getattr(run, field) == value


@pytest.mark.django_db
def test_ai_run_public_strings_redact_standalone_and_encoded_credentials(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="encoded-credentials")
    basic_value = "dXNlcjpwYXNz"
    sensitive_values = [
        "Bearer STANDALONE-BEARER-SENTINEL",
        "bearer\tTAB-SENTINEL",
        f"Basic {basic_value}",
        'basic "QUOTED BASIC SENTINEL"',
        "https://x/?access%5Ftoken=ENCODED-KEY-SENTINEL",
        "https://x/#%61pi_key=ENCODED-NAME-SENTINEL",
        "https://x/?client%5Fsecret=CLIENT-SENTINEL",
        "https://x/?access%255Ftoken=DOUBLE-ENCODED-SENTINEL",
        "https://x/?ACCESS%EF%BC%BFToken=UNICODE-KEY-SENTINEL",
        "https://x/?access%ZZtoken=MALFORMED-PERCENT-SENTINEL",
        "https://x/?api%FFkey=INVALID-UTF8-SENTINEL",
    ]
    stored = {
        "input_snapshot": {
            "brief_id": "brief-safe",
            "keywords": [*sensitive_values, "token budget", "password policy"],
        },
        "output_json": {
            "title": sensitive_values[0],
            "body": sensitive_values[1],
            "cta": sensitive_values[2],
            "concept_codes": [*sensitive_values, "token budget", "password policy"],
        },
        "human_correction": {
            "title": sensitive_values[3],
            "body": sensitive_values[4],
            "cta": sensitive_values[5],
            "concept_codes": [*sensitive_values, "token budget", "password policy"],
        },
    }
    original = deepcopy(stored)
    with ai_audit_writes():
        AIRun.objects.filter(pk=run.pk).update(**stored)

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    sentinels = [
        "standalone-bearer-sentinel", "tab-sentinel", "quoted basic sentinel",
        "encoded-key-sentinel", "encoded-name-sentinel", "client-sentinel",
        "double-encoded-sentinel", "unicode-key-sentinel",
        "malformed-percent-sentinel", "invalid-utf8-sentinel",
    ]
    for sentinel in sentinels:
        encoded = "".join(f"%{byte:02X}" for byte in sentinel.encode()).casefold()
        assert sentinel not in serialized
        assert encoded not in serialized
        assert quote(encoded, safe="").casefold() not in serialized
    assert basic_value.casefold() not in serialized
    assert "token budget" in data["output_json"]["concept_codes"]
    assert "password policy" in data["output_json"]["concept_codes"]
    assert "token budget" in data["human_correction"]["concept_codes"]
    run.refresh_from_db()
    for field, value in original.items():
        assert getattr(run, field) == value


@pytest.mark.django_db
def test_ai_run_public_strings_fail_closed_beyond_percent_decode_budget(ai_api):
    own, _other, _user, client = ai_api
    run = make_run(own, suffix="excessive-encoding")
    decode_budget = 3

    def encoded_access_token(depth: int, sentinel: str) -> str:
        separator = "%5F"
        for _round in range(depth - 1):
            separator = separator.replace("%", "%25")
        return f"https://x/?access{separator}token={sentinel}"

    depth4 = encoded_access_token(decode_budget + 1, "DEPTH4-SENTINEL")
    depth6 = encoded_access_token(decode_budget + 3, "DEPTH6-SENTINEL")
    assert depth4 == "https://x/?access%2525255Ftoken=DEPTH4-SENTINEL"
    assert depth6 == "https://x/?access%25252525255Ftoken=DEPTH6-SENTINEL"
    stored = {
        "input_snapshot": {
            "brief_id": "brief-safe",
            "keywords": [depth4, depth6, "token budget", "password policy"],
        },
        "output_json": {
            "title": depth4,
            "body": depth6,
            "cta": "safe cta",
            "concept_codes": [depth4, depth6, "token budget", "password policy"],
        },
        "human_correction": {
            "title": depth6,
            "body": depth4,
            "cta": "safe correction",
            "concept_codes": [depth4, depth6, "token budget", "password policy"],
        },
    }
    original = deepcopy(stored)
    with ai_audit_writes():
        AIRun.objects.filter(pk=run.pk).update(**stored)

    response = client.get(f"/api/v1/ai-runs/{run.id}")

    assert response.status_code == 200
    data = response.json()
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    for value, depth, sentinel in (
        (depth4, decode_budget + 1, "depth4-sentinel"),
        (depth6, decode_budget + 3, "depth6-sentinel"),
    ):
        decoded_forms = [value]
        for _round in range(depth):
            decoded_forms.append(unquote(decoded_forms[-1]))
        assert decoded_forms[-1].startswith("https://x/?access_token=")
        assert len(set(decoded_forms)) == depth + 1
        assert sentinel not in serialized
        for decoded_form in decoded_forms:
            assert decoded_form.casefold() not in serialized
    assert "token budget" in data["output_json"]["concept_codes"]
    assert "password policy" in data["human_correction"]["concept_codes"]
    run.refresh_from_db()
    for field, value in original.items():
        assert getattr(run, field) == value


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
