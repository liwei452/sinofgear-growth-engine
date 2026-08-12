import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.content.models import MasterContent, content_writes
from apps.content.services import (
    approve_content, create_generated_master, create_platform_content,
    create_master_revision, create_platform_revision,
)
from apps.identity.models import Membership, Organization, Role
from apps.ai.models import AIExecutionIntent, AIProviderConfiguration, PromptVersion
from apps.ai.services import PromptVersionService
from apps.ai.orchestration import (
    GenerationPreflightError,
    _validate_generation_input,
    _validate_job_routing,
    execute_generation_job,
)
from integrations.ai.providers import provider_registry
from apps.campaigns.generation_schema import generation_input_errors


def _client(organization, role_code):
    role = {
        Role.Code.ADMINISTRATOR: Role.objects.create_administrator,
        Role.Code.OPERATOR: Role.objects.create_operator,
        Role.Code.REVIEWER: Role.objects.create_reviewer,
        Role.Code.READ_ONLY: Role.objects.create_read_only,
    }[role_code]()
    user = get_user_model().objects.create_user(
        username=f"content-api-{role_code}", password="password"
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.mark.parametrize(
    ("role_code", "can_manage", "can_review"),
    [
        (Role.Code.ADMINISTRATOR, True, True),
        (Role.Code.OPERATOR, True, False),
        (Role.Code.REVIEWER, False, True),
        (Role.Code.READ_ONLY, False, False),
    ],
)
def test_content_role_permissions(content_provenance, role_code, can_manage, can_review):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    client = _client(organization, role_code)

    detail = client.get(f"/api/v1/master-contents/{content.id}")
    revision = client.post(
        f"/api/v1/master-contents/{content.id}/revisions",
        {"payload": {**content.payload, "title": "Edited"}}, format="json",
    )
    approve = client.post(
        f"/api/v1/master-contents/{content.id}/approve", {"comment": "ok"},
        format="json",
    )

    assert detail.status_code == 200
    assert revision.status_code == (201 if can_manage else 403)
    expected_approve = 409 if can_manage and can_review else (200 if can_review else 403)
    assert approve.status_code == expected_approve


def test_content_cross_organization_is_non_leaking_404(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    other = Organization.objects.create(name="Other", slug="content-other")
    client = _client(other, Role.Code.ADMINISTRATOR)

    assert client.get(f"/api/v1/master-contents/{content.id}").status_code == 404
    assert client.post(
        f"/api/v1/master-contents/{content.id}/approve", {}, format="json"
    ).status_code == 404


def test_content_openapi_documents_generation_and_review_actions(content_provenance):
    organization, *_ = content_provenance
    schema = _client(organization, Role.Code.READ_ONLY).get("/api/v1/schema").json()

    assert "post" in schema["paths"]["/api/v1/content-briefs/{brief_id}/generate-master-content"]
    assert "get" in schema["paths"]["/api/v1/master-contents"]
    assert "post" in schema["paths"]["/api/v1/master-contents/{content_id}/approve"]
    assert "post" in schema["paths"]["/api/v1/master-contents/{content_id}/generate-platform-content"]
    assert "get" in schema["paths"]["/api/v1/platform-contents"]


def test_corrupt_provenance_is_omitted_and_detail_is_404(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    with content_writes():
        type(content).objects.filter(pk=content.pk).update(
            provenance={**content.provenance, "brief_version": content.brief_version + 1}
        )
    client = _client(organization, Role.Code.READ_ONLY)

    assert client.get(f"/api/v1/master-contents/{content.id}").status_code == 404
    assert all(
        row["id"] != str(content.id)
        for row in client.get("/api/v1/master-contents").json()["results"]
    )


def test_invalid_revision_payload_returns_controlled_400(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    client = _client(organization, Role.Code.OPERATOR)

    response = client.post(
        f"/api/v1/master-contents/{content.id}/revisions",
        {"payload": {**content.payload, "concept_codes": ["DUP", " DUP "]}},
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) == {"errors", "code", "message", "recovery_action"}


def test_master_current_head_is_authoritative_across_filters_and_detail(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    source = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    revision = create_master_revision(
        source, actor=actor, payload={**source.payload, "title": "Current head"},
    )
    client = _client(organization, Role.Code.READ_ONLY)

    filtered = client.get("/api/v1/master-contents?status=IN_REVIEW&page_size=1")

    assert filtered.status_code == 200
    assert filtered.json()["results"] == [{
        **filtered.json()["results"][0], "is_current_head": False,
    }]
    assert filtered.json()["results"][0]["id"] == str(source.id)
    assert client.get(
        f"/api/v1/master-contents/{source.id}"
    ).json()["is_current_head"] is False
    assert client.get(
        f"/api/v1/master-contents/{revision.id}"
    ).json()["is_current_head"] is True


def test_cross_organization_successor_does_not_change_current_head(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    source = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    other = Organization.objects.create(name="Corrupt Other", slug="corrupt-other")
    with content_writes():
        MasterContent.objects.create(
            organization=other,
            brief=brief,
            brief_version=source.brief_version,
            generation_job=job,
            ai_run=run,
            lineage_id=source.lineage_id,
            previous_version=source,
            version=source.version + 1,
            payload={**source.payload, "title": "Cross-org corruption"},
            provenance=source.provenance,
            status=MasterContent.Status.DRAFT,
            created_by=actor,
        )

    response = _client(organization, Role.Code.READ_ONLY).get(
        f"/api/v1/master-contents/{source.id}"
    )

    assert response.status_code == 200
    assert response.json()["is_current_head"] is True


def test_platform_list_consistency_query_count_is_page_size_independent(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor), actor=actor
    )
    selected = brief.platform_links.get().platform
    head = create_platform_content(master, platform=selected, actor=actor)
    client = _client(organization, Role.Code.READ_ONLY)
    with CaptureQueriesContext(connection) as single:
        response = client.get("/api/v1/platform-contents?page_size=50")
    assert response.status_code == 200
    for index in range(5):
        head = create_platform_revision(
            head, actor=actor, payload={**head.payload, "title": f"revision {index}"}
        )
    with CaptureQueriesContext(connection) as many:
        response = client.get("/api/v1/platform-contents?page_size=50")
    assert response.status_code == 200
    assert len(many) == len(single)


def test_noncanonical_raw_payload_is_hidden_from_all_boundaries(content_provenance):
    organization, actor, brief, job, run = content_provenance
    master = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    client = _client(organization, Role.Code.ADMINISTRATOR)
    with content_writes():
        type(master).objects.filter(pk=master.pk).update(
            payload={**master.payload, "title": f" {master.payload['title']} "}
        )

    assert client.get(f"/api/v1/master-contents/{master.id}").status_code == 404
    assert client.post(
        f"/api/v1/master-contents/{master.id}/approve", {"comment": "ok"}, format="json"
    ).status_code == 404
    assert all(
        row["id"] != str(master.id)
        for row in client.get("/api/v1/master-contents").json()["results"]
    )


def test_illegal_status_is_hidden_for_both_content_types(content_provenance):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor), actor=actor
    )
    platform = create_platform_content(
        master, platform=brief.platform_links.get().platform, actor=actor
    )
    with content_writes():
        type(master).objects.filter(pk=master.pk).update(status="FORGED")
        type(platform).objects.filter(pk=platform.pk).update(status="FORGED")
    client = _client(organization, Role.Code.ADMINISTRATOR)

    for prefix, content in (("master", master), ("platform", platform)):
        assert client.get(f"/api/v1/{prefix}-contents/{content.id}").status_code == 404
        assert client.post(
            f"/api/v1/{prefix}-contents/{content.id}/approve",
            {"comment": "ok"}, format="json",
        ).status_code == 404
        assert all(
            row["id"] != str(content.id)
            for row in client.get(f"/api/v1/{prefix}-contents").json()["results"]
        )


def test_master_revision_rejects_platform_payload_at_serializer(content_provenance):
    organization, actor, brief, job, run = content_provenance
    master = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    client = _client(organization, Role.Code.OPERATOR)

    response = client.post(
        f"/api/v1/master-contents/{master.id}/revisions",
        {"payload": {**master.payload, "platform_code": "SELECTED"}}, format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) == {"errors", "code", "message", "recovery_action"}


def test_platform_revision_requires_platform_payload_at_serializer(content_provenance):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor), actor=actor
    )
    platform = create_platform_content(
        master, platform=brief.platform_links.get().platform, actor=actor
    )
    client = _client(organization, Role.Code.OPERATOR)
    payload = {key: value for key, value in platform.payload.items() if key != "platform_code"}

    response = client.post(
        f"/api/v1/platform-contents/{platform.id}/revisions",
        {"payload": payload}, format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) == {"errors", "code", "message", "recovery_action"}


def test_generate_rejects_model_injection_and_operator_enhanced_analysis(content_provenance):
    organization, _actor, brief, _job, _run = content_provenance
    client = _client(organization, Role.Code.OPERATOR)

    model = client.post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content",
        {"model": "deepseek-v4-pro"}, format="json",
    )
    enhanced = client.post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content",
        {"enhanced_analysis": True}, format="json",
    )

    assert model.status_code == enhanced.status_code == 400
    assert not AIExecutionIntent.objects.filter(organization=organization).exists()


def test_generate_admin_freezes_intent_with_job_transactionally(
    content_provenance, monkeypatch, django_capture_on_commit_callbacks,
):
    organization, _actor, brief, _job, _run = content_provenance
    client = _client(organization, Role.Code.ADMINISTRATOR)
    AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
        key_suffix="safe",
    )
    PromptVersionService.create(
        purpose="CONTENT_GENERATE", code="deepseek-content", provider="deepseek",
        model="deepseek-v4-flash", template="Promote {product_name}",
        output_schema={"type": "object"}, status=PromptVersion.Status.PUBLISHED,
    )
    snapshot = {
        "organization_id": str(organization.id),
        "brief_id": str(brief.id),
        "products": [{"name_en": "Helical gear"}],
        "ontology_snapshot": {"concept_versions": []},
    }
    monkeypatch.setattr(
        "apps.content.views.build_content_generation_input",
        lambda _brief_id: type("Snapshot", (), {"to_dict": lambda self: snapshot})(),
    )
    dispatched = []
    monkeypatch.setattr(
        "apps.content.tasks.generate_master_content_job.delay",
        lambda *args: dispatched.append(args),
    )
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/content-briefs/{brief.id}/generate-master-content",
            {"enhanced_analysis": True}, format="json",
        )

    assert response.status_code == 202
    intent = AIExecutionIntent.objects.get(job_id=response.json()["job_id"])
    assert (intent.model, intent.thinking_enabled) == ("deepseek-v4-pro", True)
    assert intent.job.input_snapshot["ai_routing"]["policy_code"] == "deepseek-routing-v1"
    assert intent.job.input_snapshot["ai_routing"]["model"] == intent.model
    assert intent.estimated_input_tokens > len("Promote Helical gear".encode("utf-8"))
    assert dispatched


def test_deepseek_content_frozen_route_passes_preflight_and_tamper_fails(
    content_provenance, monkeypatch, django_capture_on_commit_callbacks,
):
    organization, _actor, brief, _job, _run = content_provenance
    client = _client(organization, Role.Code.ADMINISTRATOR)
    AIProviderConfiguration.objects.create(
        organization=organization, connection_state="CONNECTED", key_suffix="safe"
    )
    PromptVersionService.create(
        purpose="CONTENT_GENERATE", code="deepseek-preflight", provider="deepseek",
        model="deepseek-v4-flash", template="Promote {product_name}",
        output_schema={"type": "object"}, status=PromptVersion.Status.PUBLISHED,
    )
    snapshot = {
        "schema_version": "1.0", "organization_id": str(organization.id),
        "brief_id": str(brief.id), "brief_version": 1,
        "campaign_id": str(brief.campaign_id), "campaign_version": 1,
        "products": [], "assets": [], "target_country": "DE", "customer_type": "OEM",
        "content_objective": "leads", "cta": "quote", "landing_page_url": "https://x.example",
        "language": "en", "keywords": [], "prohibited_claims": [], "selling_points": [],
        "advantages": [], "target_platforms": [],
        "ontology_snapshot": {"organization_id": str(organization.id), "concept_versions": [],
          "relation_versions": [], "evidence_references": [], "generated_at": "2026-08-12T00:00:00Z"},
        "generated_at": "2026-08-12T00:00:00Z",
    }
    # Use valid non-empty objects from the real fixture builder schema via focused substitutions.
    snapshot["products"] = [{
        "product_id": str(brief.id), "product_version": 1, "name_zh": "", "name_en": "Gear",
        "module_min": "1", "module_max": "2", "tooth_count_min": 10, "tooth_count_max": 20,
        "pressure_angle": "20", "accuracy_grade": "DIN6", "heat_treatment": "",
        "surface_treatment": "", "manufacturing_capabilities": [], "inspection_capabilities": [],
        "moq": 1, "lead_time": "2w", "landing_page_url": "", "status": "ACTIVE",
        "concept_versions": [],
    }]
    snapshot["target_platforms"] = [{
        "platform_id": str(brief.id), "code": "LINKEDIN", "name": "LinkedIn",
        "capability_codes": [],
    }]
    monkeypatch.setattr(
        "apps.content.views.build_content_generation_input",
        lambda _id: type("S", (), {"to_dict": lambda self: snapshot})(),
    )
    monkeypatch.setattr("apps.content.tasks.generate_master_content_job.delay", lambda *_: None)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/api/v1/content-briefs/{brief.id}/generate-master-content", {}, format="json"
        )
    assert response.status_code == 202
    intent = AIExecutionIntent.objects.get(job_id=response.json()["job_id"])
    errors = generation_input_errors(intent.job.input_snapshot)
    assert not errors, [error.message for error in errors]
    _validate_generation_input(intent.job.input_snapshot, organization_id=organization.id)
    class Provider:
        def generate(self, *, prompt, schema):
            return {}

    provider_registry.register("deepseek", Provider(), replace=True)
    run = execute_generation_job(
        intent.job_id,
        prompt_version_id=PromptVersion.objects.get(code="deepseek-preflight").id,
    )
    assert run.status == "SUCCEEDED"
    tampered_route = {
        **intent.job.input_snapshot["ai_routing"],
        "model": "deepseek-v4-pro",
        "thinking_enabled": True,
    }
    tampered = {**intent.job.input_snapshot, "ai_routing": tampered_route}
    with pytest.raises(GenerationPreflightError):
        _validate_job_routing(intent.job, tampered)
