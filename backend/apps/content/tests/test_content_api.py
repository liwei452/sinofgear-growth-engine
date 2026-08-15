import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.campaigns.models import ContentBriefPlatform
from apps.campaigns.services import mark_content_brief_ready, revise_content_brief
from apps.content.models import MasterContent, PlatformContent, content_writes
from apps.content.services import (
    approve_content, create_generated_master, create_platform_content,
    create_master_revision, create_platform_revision,
)
from apps.growth.models import ChannelPackage
from apps.growth.services import prepare_channel_package_from_platform_content
from apps.identity.models import Membership, Organization, Role
from apps.jobs.services import JobService
from apps.jobs.models import Job
from apps.platforms.models import Platform


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


def _version_two_master(content_provenance):
    organization, actor, brief, source_job, _source_run = content_provenance
    brief = revise_content_brief(brief.id, creator=actor)
    selected = brief.platform_links.get().platform
    selected.code = "LINKEDIN"
    selected.name = "LinkedIn"
    selected.save(update_fields=["code", "name"])
    platforms = [selected]
    for code in ("FACEBOOK", "INSTAGRAM", "TIKTOK"):
        platform = Platform.objects.create(code=code, name=code.title())
        ContentBriefPlatform.objects.create(
            organization=organization, brief=brief, platform=platform,
        )
        platforms.append(platform)
    brief = mark_content_brief_ready(brief.id, reviewer=actor)
    fact_id = source_job.input_snapshot["verified_product_facts"][0]["fact_id"]
    variants = []
    for index, platform in enumerate(platforms, start=1):
        variant = {
            "platform_code": platform.code,
            "language": "en",
            "title": f"{platform.code} title",
            "body": f"Distinct {platform.code} body {index}",
            "cta": "Request a quote",
            "landing_page_url": "https://example.com/gears",
            "hashtags": [f"#{platform.code.title()}Gears"],
            "evidence_fact_ids": [fact_id],
        }
        if platform.code == "TIKTOK":
            variant.update({
                "duration_seconds": 42,
                "aspect_ratio": "9:16",
                "script": "Target-language TikTok script",
                "shot_list": [{
                    "scene": "1",
                    "visual": "Gear inspection close-up",
                    "on_screen_text": "Verified precision process",
                }],
                "voiceover": "Target-language voiceover",
                "voiceover_language": "en",
                "subtitles": "Target-language subtitles",
                "subtitle_language": "en",
            })
        variants.append(variant)
    output = {
        "schema_version": 2,
        "language": "en",
        "title": "Evidence-backed master",
        "body": "Master body is not a platform body.",
        "cta": "Request a quote",
        "landing_page_url": "https://example.com/gears",
        "concept_codes": [],
        "evidence_fact_ids": [fact_id],
        "internal_translation_zh": "仅供内部审核，不得发布。",
        "platform_variants": variants,
    }
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={
            "brief_id": str(brief.id),
            "brief_version": brief.version,
            "verified_product_facts": source_job.input_snapshot["verified_product_facts"],
        },
        created_by=actor,
    )
    claimed = JobService.claim(worker_id="v2-content-test", job_id=job.id)
    prompt = PromptVersion.objects.get(purpose="CONTENT_GENERATE", version=2)
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=job.attempt,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot=job.input_snapshot,
            status=AIRun.Status.SUCCEEDED,
            output_json=output,
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
    master = create_generated_master(
        brief=brief, job=claimed, ai_run=run, actor=actor,
    )
    JobService.succeed(
        job.id,
        claim_token=claimed.claim_token,
        result_reference={
            "type": "master_content", "id": str(master.id), "version": 1,
        },
    )
    master.refresh_from_db()
    return approve_content(master, actor=actor), actor, platforms


def test_version_two_master_creates_distinct_reviewable_platform_variants(
    content_provenance,
):
    master, actor, platforms = _version_two_master(content_provenance)

    rows = [
        create_platform_content(master, platform=platform, actor=actor)
        for platform in platforms
    ]

    assert [row.payload["body"] for row in rows] == [
        "Distinct LINKEDIN body 1",
        "Distinct FACEBOOK body 2",
        "Distinct INSTAGRAM body 3",
        "Distinct TIKTOK body 4",
    ]
    assert all(row.payload["schema_version"] == 2 for row in rows)
    assert all(row.payload["language"] == "en" for row in rows)
    assert all("internal_translation_zh" not in row.payload for row in rows)


def test_tiktok_package_copies_the_approved_target_language_structure(
    content_provenance,
):
    master, actor, platforms = _version_two_master(content_provenance)
    tiktok = next(platform for platform in platforms if platform.code == "TIKTOK")
    content = approve_content(
        create_platform_content(master, platform=tiktok, actor=actor), actor=actor,
    )

    package, created = prepare_channel_package_from_platform_content(content=content)

    assert created is True
    assert package.payload["language"] == "en"
    assert package.payload["duration_seconds"] == 42
    assert package.payload["shot_list"] == content.payload["shot_list"]
    assert package.payload["voiceover"] == "Target-language voiceover"
    assert package.payload["subtitles"] == "Target-language subtitles"
    assert package.payload["hashtags"] == ["#TiktokGears"]
    assert "english_voiceover" not in package.payload
    assert "chinese_subtitles" not in package.payload
    assert "internal_translation_zh" not in package.payload


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


def test_master_archive_is_reversible_and_hidden_from_default_list(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    client = _client(organization, Role.Code.ADMINISTRATOR)

    archived = client.post(
        f"/api/v1/master-contents/{content.id}/archive", {"comment": "unused"}, format="json"
    )
    assert archived.status_code == 200
    assert archived.data["status"] == "ARCHIVED"
    assert client.get("/api/v1/master-contents").data["results"] == []
    assert client.get("/api/v1/master-contents?status=ARCHIVED").data["results"][0]["id"] == str(content.id)
    restored = client.post(f"/api/v1/master-contents/{content.id}/restore", {}, format="json")
    assert restored.status_code == 200
    assert restored.data["status"] == "IN_REVIEW"


def test_master_detail_exposes_bounded_verified_fact_evidence(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    response = _client(organization, Role.Code.READ_ONLY).get(
        f"/api/v1/master-contents/{content.id}"
    )

    assert response.status_code == 200
    assert response.data["evidence_summary"] == [{
        "fact_id": "11111111-1111-4111-8111-111111111111",
        "field_name": "process",
        "value": "Gear grinding",
        "source_filename": "gear-catalog.pdf",
        "source_page": 2,
        "source_excerpt": "Process: Gear grinding",
        "is_demo": True,
    }]


def test_content_openapi_documents_generation_and_review_actions(content_provenance):
    organization, *_ = content_provenance
    schema = _client(organization, Role.Code.READ_ONLY).get("/api/v1/schema").json()

    assert "post" in schema["paths"]["/api/v1/content-briefs/{brief_id}/generate-master-content"]
    assert "get" in schema["paths"]["/api/v1/master-contents"]
    assert "post" in schema["paths"]["/api/v1/master-contents/{content_id}/approve"]
    assert "post" in schema["paths"]["/api/v1/master-contents/{content_id}/generate-platform-content"]
    assert "get" in schema["paths"]["/api/v1/platform-contents"]


def test_generation_discloses_fake_provider_before_work_starts(content_provenance):
    organization, _actor, brief, _job, _run = content_provenance
    response = _client(organization, Role.Code.ADMINISTRATOR).post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content", {}, format="json",
    )

    assert response.status_code == 202
    assert response.data["generation_mode"] == "FAKE_OFFLINE"
    assert response.data["generation_label"] == "Fake / 离线演示生成"


def test_generation_does_not_reschedule_completed_idempotent_job(
    content_provenance, monkeypatch,
):
    organization, _actor, brief, _fixture_job, _run = content_provenance
    dispatched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.content.views.generate_master_content_job.delay",
        lambda job_id, prompt_id: dispatched.append((job_id, prompt_id)),
    )
    client = _client(organization, Role.Code.ADMINISTRATOR)

    first = client.post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content", {}, format="json",
    )
    claimed = JobService.claim(
        worker_id="content-idempotency-test", job_id=first.data["job_id"],
    )
    JobService.succeed(
        claimed.id,
        claim_token=claimed.claim_token,
        result_reference={"type": "master_content", "id": "result-1"},
    )

    response = client.post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content", {}, format="json",
    )

    assert response.status_code == 202
    assert response.data["job_id"] == first.data["job_id"]
    assert dispatched == []


@override_settings(PRODUCT_AI_PROVIDER="deepseek", PRODUCT_AI_MODEL="deepseek-chat")
def test_generation_requires_key_before_claiming_real_ai(content_provenance, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    organization, _actor, brief, _job, _run = content_provenance
    response = _client(organization, Role.Code.ADMINISTRATOR).post(
        f"/api/v1/content-briefs/{brief.id}/generate-master-content", {}, format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "CONFIGURATION_REQUIRED"
    assert "not configured" in response.data["message"]


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
