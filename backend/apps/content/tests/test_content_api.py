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
    assert set(response.json()) == {"errors"}


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
    assert set(response.json()) == {"errors"}


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
    assert set(response.json()) == {"errors"}
