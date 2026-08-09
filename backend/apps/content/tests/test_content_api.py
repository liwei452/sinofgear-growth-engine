import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.content.services import create_generated_master
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
    assert approve.status_code == (200 if can_review else 403)


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
