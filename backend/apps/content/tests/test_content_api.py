import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.content.models import MasterContent, PlatformContent, content_writes
from apps.content.services import (
    approve_content, create_generated_master, create_platform_content,
    create_master_revision, create_platform_revision,
)
from apps.growth.models import ChannelPackage
from apps.growth.services import prepare_channel_package_from_platform_content
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


@pytest.mark.parametrize("channel", ["LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"])
def test_approved_platform_content_can_prepare_one_reviewable_publish_package(
    content_provenance, channel,
):
    organization, actor, brief, _job, _run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=_job, ai_run=_run, actor=actor),
        actor=actor,
    )
    platform = brief.platform_links.get().platform
    platform.code = channel
    platform.name = channel.title()
    platform.save(update_fields=["code", "name"])
    content = create_platform_content(master, platform=platform, actor=actor)
    content = approve_content(content, actor=actor)
    client = _client(organization, Role.Code.ADMINISTRATOR)

    first = client.post(
        f"/api/v1/growth/channel-packages/from-platform-content/{content.id}",
        {}, format="json",
    )
    second = client.post(
        f"/api/v1/growth/channel-packages/from-platform-content/{content.id}",
        {}, format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert ChannelPackage.objects.filter(organization=organization).count() == 1
    package = ChannelPackage.objects.get(organization=organization)
    assert package.source_platform_content_id == content.id
    assert package.channel == channel
    assert package.status == "AWAITING_REVIEW"
    assert package.is_demo is True
    expected_payload = {
        "title": content.payload["title"],
        "body": content.payload["body"],
        "cta": content.payload["cta"],
        "platform_code": channel,
        "source_platform_content_id": str(content.id),
        "source_platform_content_version": content.version,
        "verified_fact_evidence": [{
            "fact_id": "11111111-1111-4111-8111-111111111111",
            "field_name": "process",
            "value": "Gear grinding",
            "source_filename": "gear-catalog.pdf",
            "source_page": 2,
            "source_excerpt": "Process: Gear grinding",
            "is_demo": True,
        }],
        "asset_references": [],
    }
    if channel == "TIKTOK":
        expected_payload.update({
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "script": content.payload["body"],
            "shot_list": [],
            "english_voiceover": content.payload["body"],
            "chinese_subtitles": "待人工补充中文字幕，批准前不得发布。",
            "hashtags": [],
            "utm": "utm_source=tiktok&utm_medium=organic&utm_campaign=manual-review",
        })
    assert package.payload == expected_payload
    refreshed = client.get(f"/api/v1/platform-contents/{content.id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["publish_package_id"] == str(package.id)


def test_channel_package_preparation_requires_approval_and_publish_permission(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor),
        actor=actor,
    )
    platform = brief.platform_links.get().platform
    platform.code = "TIKTOK"
    platform.save(update_fields=["code"])
    content = create_platform_content(master, platform=platform, actor=actor)
    endpoint = f"/api/v1/growth/channel-packages/from-platform-content/{content.id}"

    pending = _client(organization, Role.Code.ADMINISTRATOR).post(endpoint, {}, format="json")
    assert pending.status_code == 409
    assert pending.json()["code"] == "CHANNEL_PACKAGE_PREPARATION_BLOCKED"
    assert not ChannelPackage.objects.filter(organization=organization).exists()

    approved = approve_content(content, actor=actor)
    forbidden = _client(organization, Role.Code.REVIEWER).post(
        f"/api/v1/growth/channel-packages/from-platform-content/{approved.id}",
        {}, format="json",
    )
    assert forbidden.status_code == 403
    assert not ChannelPackage.objects.filter(organization=organization).exists()


def test_channel_package_preparation_hides_cross_organization_content(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor),
        actor=actor,
    )
    platform = brief.platform_links.get().platform
    platform.code = "INSTAGRAM"
    platform.save(update_fields=["code"])
    content = approve_content(
        create_platform_content(master, platform=platform, actor=actor), actor=actor,
    )
    other = Organization.objects.create(name="Other Publisher", slug="other-publisher")

    response = _client(other, Role.Code.ADMINISTRATOR).post(
        f"/api/v1/growth/channel-packages/from-platform-content/{content.id}",
        {}, format="json",
    )

    assert response.status_code == 404
    assert not ChannelPackage.objects.exists()


def test_combined_manual_export_rejects_a_superseded_platform_content(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor),
        actor=actor,
    )
    platform = brief.platform_links.get().platform
    platform.code = "LINKEDIN"
    platform.save(update_fields=["code"])
    content = approve_content(
        create_platform_content(master, platform=platform, actor=actor), actor=actor,
    )
    package, _ = prepare_channel_package_from_platform_content(content=content)
    package.status = "APPROVED"
    package.save(update_fields=["status", "updated_at"])
    packages = [package]
    for channel in ("FACEBOOK", "INSTAGRAM", "TIKTOK"):
        packages.append(ChannelPackage.objects.create(
            organization=organization,
            channel=channel,
            payload={"title": channel},
            status="APPROVED",
            is_demo=True,
        ))
    client = _client(organization, Role.Code.ADMINISTRATOR)
    payload = {"package_ids": [str(item.id) for item in packages]}
    with content_writes():
        PlatformContent.objects.filter(pk=content.pk).update(
            status=PlatformContent.Status.PUBLISHED,
        )
    published_export = client.post(
        "/api/v1/growth/channel-packages/manual-export-all", payload, format="json",
    )
    assert published_export.status_code == 200

    create_platform_revision(content, payload={**content.payload, "title": "New version"}, actor=actor)

    response = client.post(
        "/api/v1/growth/channel-packages/manual-export-all",
        payload,
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "MANUAL_EXPORT_NOT_READY"
    assert "新版本" in response.json()["message"]


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
