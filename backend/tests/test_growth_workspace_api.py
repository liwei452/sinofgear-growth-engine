import hashlib
import io
import json
import zipfile

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


@pytest.fixture
def growth_client(db):
    organization = Organization.objects.create(name="SinofGear Demo", slug="growth-demo")
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(username="growth-owner", password="safe-test-password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, organization


@pytest.fixture
def growth_publish_ready(growth_client):
    client, organization = growth_client
    from apps.growth.models import ChannelPackage

    packages = []
    for index, channel in enumerate(("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"), start=1):
        platform = Platform.objects.create(code=channel, name=channel.title())
        credential = ConnectorCredential.objects.create(
            organization=organization,
            platform=platform,
            secret_reference=f"test-only://{channel.lower()}",
            granted_scopes=[AccountCapability.PUBLISH],
        )
        SocialAccount.objects.create(
            organization=organization,
            platform=platform,
            credential=credential,
            external_id=f"growth-demo-{index}",
            display_name=f"{channel.title()} Demo",
            publish_mode=SocialAccount.PublishMode.API_AUTO,
            connector_metadata={
                "fixture": "phase-a-e2e",
                "mock_outcome": "fail_once" if channel == "TIKTOK" else "success",
            },
        )
        packages.append(ChannelPackage.objects.create(
            organization=organization,
            channel=channel,
            payload={"title": f"{channel} inspection proof"},
            status="APPROVED",
            is_demo=True,
        ))
    from apps.growth.promotion_plan import approve_promotion_plan

    owner = get_user_model().objects.get(username="growth-owner")
    approve_promotion_plan(organization=organization, actor=owner)
    return client, organization, packages


@pytest.mark.django_db
def test_one_click_publish_api_is_idempotent_and_retries_only_failure(growth_publish_ready):
    client, _organization, packages = growth_publish_ready
    payload = {"package_ids": [str(package.id) for package in packages]}

    first = client.post(
        "/api/v1/growth/publish-batches", payload, format="json",
        HTTP_IDEMPOTENCY_KEY="growth-api-demo-1",
    )
    replay = client.post(
        "/api/v1/growth/publish-batches", payload, format="json",
        HTTP_IDEMPOTENCY_KEY="growth-api-demo-1",
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.data["id"] == first.data["id"]
    assert first.data["status"] == "CONFIGURATION_REQUIRED"
    assert first.data["is_demo"] is True
    assert first.data["data_label"] == "Demo / Fake 发布结果"
    assert {item["channel"] for item in first.data["items"]} == {
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK",
    }
    assert all(
        item["error_code"] == "DEMO_ONLY_NO_EXTERNAL_PUBLISH"
        for item in first.data["items"]
    )
    assert all(item["status"] == "SKIPPED" for item in first.data["items"])

    retried = client.post(
        f"/api/v1/growth/publish-batches/{first.data['id']}/retry-failed", {}, format="json",
    )
    detail = client.get(f"/api/v1/growth/publish-batches/{first.data['id']}")

    assert retried.status_code == 200
    assert retried.data["status"] == "CONFIGURATION_REQUIRED"
    assert detail.data == retried.data
    attempts = {item["channel"]: item["attempt_number"] for item in retried.data["items"]}
    assert attempts == {"FACEBOOK": 0, "INSTAGRAM": 0, "LINKEDIN": 0, "TIKTOK": 0}
    assert all(
        item["external_post_url"] == ""
        for item in retried.data["items"]
    )


@pytest.mark.django_db
def test_publish_batch_api_requires_a_valid_key_and_package_list(growth_publish_ready):
    client, _organization, packages = growth_publish_ready

    missing_key = client.post(
        "/api/v1/growth/publish-batches",
        {"package_ids": [str(packages[0].id)]},
        format="json",
    )
    empty = client.post(
        "/api/v1/growth/publish-batches", {"package_ids": []}, format="json",
        HTTP_IDEMPOTENCY_KEY="growth-api-empty",
    )

    assert missing_key.status_code == 400
    assert missing_key.data["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert empty.status_code == 400
    assert empty.data["code"] == "INVALID_PACKAGE_SELECTION"


@pytest.mark.django_db
def test_publish_batch_api_does_not_enumerate_foreign_packages(growth_publish_ready):
    client, _organization, _packages = growth_publish_ready
    from apps.growth.models import ChannelPackage

    foreign = Organization.objects.create(name="Foreign publishing", slug="foreign-publishing-api")
    secret = ChannelPackage.objects.create(
        organization=foreign,
        channel="LINKEDIN",
        payload={"title": "foreign secret"},
        status="APPROVED",
        is_demo=True,
    )

    response = client.post(
        "/api/v1/growth/publish-batches",
        {"package_ids": [str(secret.id)]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="growth-api-foreign",
    )

    assert response.status_code == 404
    assert b"foreign secret" not in response.content


@pytest.mark.django_db
def test_company_facts_list_is_organization_scoped(growth_client):
    client, organization = growth_client
    from apps.growth.models import FieldProvenance

    FieldProvenance.objects.create(
        organization=organization,
        field_name="accuracy_grade",
        field_value="DIN 6",
        source_label="Product library",
        verification_status="NEEDS_EVIDENCE",
    )
    foreign = Organization.objects.create(name="Foreign", slug="foreign-facts-list")
    FieldProvenance.objects.create(
        organization=foreign,
        field_name="secret_capacity",
        field_value="hidden",
        source_label="private",
        verification_status="NEEDS_CONFIRMATION",
    )

    response = client.get("/api/v1/growth/company-facts")

    assert response.status_code == 200
    assert [item["field_name"] for item in response.data] == ["accuracy_grade"]
    assert "hidden" not in str(response.data)


@pytest.mark.django_db
def test_follow_up_is_idempotent_and_draft_is_never_sent(growth_client):
    client, organization = growth_client
    from apps.growth.models import OutreachDraft, TargetAccount

    account = TargetAccount.objects.create(
        organization=organization, name="PackTech GmbH", country="Germany", is_demo=True,
    )

    first = client.post(f"/api/v1/growth/opportunities/{account.id}/follow-up", {}, format="json")
    second = client.post(f"/api/v1/growth/opportunities/{account.id}/follow-up", {}, format="json")
    draft = client.post(f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["id"] == second.data["id"]
    assert draft.status_code == 201
    assert draft.data["status"] == "DRAFT"
    assert "English draft" in draft.data
    assert "Chinese explanation" in draft.data
    assert draft.data["delivery"] == "NEVER_SENT"
    assert OutreachDraft.objects.get(id=draft.data["id"]).status == OutreachDraft.Status.DRAFT


@pytest.mark.django_db
def test_growth_actions_do_not_enumerate_foreign_accounts(growth_client):
    client, _organization = growth_client
    from apps.growth.models import TargetAccount

    foreign = Organization.objects.create(name="Foreign", slug="foreign-action")
    account = TargetAccount.objects.create(organization=foreign, name="Foreign secret", country="US")

    follow_up = client.post(f"/api/v1/growth/opportunities/{account.id}/follow-up", {}, format="json")
    draft = client.post(f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json")

    assert follow_up.status_code == 404
    assert draft.status_code == 404
    assert "Foreign secret" not in follow_up.content.decode()
    assert "Foreign secret" not in draft.content.decode()


@pytest.mark.django_db
def test_channel_package_approval_and_metric_backfill_are_persisted_without_publish(growth_client):
    client, organization = growth_client
    from apps.growth.models import ChannelPackage, MetricReceipt

    package = ChannelPackage.objects.create(
        organization=organization,
        channel="TIKTOK",
        payload={"duration_seconds": 30, "aspect_ratio": "9:16", "title": "DIN 6 proof"},
        is_demo=True,
    )

    approved = client.post(f"/api/v1/growth/channel-packages/{package.id}/approve", {}, format="json")
    receipt = client.post(
        "/api/v1/growth/metric-receipts",
        {"channel": "TIKTOK", "payload": {"views": 6820, "clicks": 186}, "is_demo": True},
        format="json",
    )

    assert approved.status_code == 200
    assert approved.data == {
        "id": str(package.id), "status": "APPROVED", "delivery": "MANUAL_ONLY",
    }
    package.refresh_from_db()
    assert package.status == "APPROVED"
    assert receipt.status_code == 201
    assert MetricReceipt.objects.get(id=receipt.data["id"]).payload["views"] == 6820


@pytest.mark.django_db
def test_verified_manual_metric_requires_source_and_observation_time(growth_client):
    client, _organization = growth_client

    blocked = client.post(
        "/api/v1/growth/metric-receipts",
        {"channel": "LINKEDIN", "payload": {"clicks": 12}, "is_demo": False},
        format="json",
    )
    saved = client.post(
        "/api/v1/growth/metric-receipts",
        {
            "channel": "LINKEDIN",
            "payload": {
                "clicks": 12,
                "source_note": "LinkedIn Page analytics manually checked by owner",
                "observed_at": "2026-08-15T09:30:00Z",
            },
            "is_demo": False,
        },
        format="json",
    )

    assert blocked.status_code == 400
    assert set(blocked.data["payload"]) == {"source_note", "observed_at"}
    assert saved.status_code == 201
    assert saved.data["is_demo"] is False
    assert saved.data["payload"]["source_note"].startswith("LinkedIn Page analytics")


@pytest.mark.django_db
def test_four_channel_content_review_is_atomic_idempotent_and_organization_scoped(growth_client):
    client, organization = growth_client
    from apps.growth.models import ChannelPackage

    packages = [
        ChannelPackage.objects.create(
            organization=organization,
            channel=channel,
            payload={"title": f"{channel} reviewed content"},
            is_demo=True,
        )
        for channel in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK")
    ]
    payload = {"package_ids": [str(package.id) for package in packages]}

    first = client.post("/api/v1/growth/channel-packages/approve-all", payload, format="json")
    replay = client.post("/api/v1/growth/channel-packages/approve-all", payload, format="json")

    assert first.status_code == 200
    assert replay.data == first.data
    assert first.data["status"] == "APPROVED"
    assert first.data["delivery"] == "MANUAL_ONLY"
    assert {item["channel"] for item in first.data["packages"]} == {
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK",
    }
    assert ChannelPackage.objects.filter(organization=organization, status="APPROVED").count() == 4

    foreign = Organization.objects.create(name="Foreign approval", slug="foreign-approval")
    secret = ChannelPackage.objects.create(
        organization=foreign, channel="TIKTOK", payload={"title": "foreign secret"}, is_demo=True,
    )
    packages[3].status = "AWAITING_REVIEW"
    packages[3].save(update_fields=["status", "updated_at"])
    blocked_ids = [str(package.id) for package in packages[:3]] + [str(secret.id)]

    blocked = client.post(
        "/api/v1/growth/channel-packages/approve-all", {"package_ids": blocked_ids}, format="json",
    )

    assert blocked.status_code == 409
    assert blocked.data["code"] == "CHANNEL_PACKAGE_SELECTION_INVALID"
    packages[3].refresh_from_db()
    secret.refresh_from_db()
    assert packages[3].status == "AWAITING_REVIEW"
    assert secret.status == "AWAITING_REVIEW"
    assert b"foreign secret" not in blocked.content


@pytest.mark.django_db
def test_only_approved_channel_package_can_be_exported_through_fake_connector(growth_client):
    client, organization = growth_client
    from apps.growth.models import ChannelPackage

    package = ChannelPackage.objects.create(
        organization=organization,
        channel="TIKTOK",
        payload={
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "title": "DIN 6 inspection proof",
            "utm": "tiktok / organic / din6-proof-demo",
        },
        is_demo=True,
    )

    blocked = client.post(
        f"/api/v1/growth/channel-packages/{package.id}/manual-export", {}, format="json",
    )
    client.post(f"/api/v1/growth/channel-packages/{package.id}/approve", {}, format="json")
    exported = client.post(
        f"/api/v1/growth/channel-packages/{package.id}/manual-export", {}, format="json",
    )

    assert blocked.status_code == 409
    assert blocked.data["code"] == "PACKAGE_REVIEW_REQUIRED"
    assert exported.status_code == 200
    assert exported.data == {
        "package_id": str(package.id),
        "channel": "TIKTOK",
        "mode": "MANUAL_PACKAGE",
        "data_label": "Demo / Fake",
        "delivery": "MANUAL_ONLY",
        "filename": "tiktok-manual-package.json",
        "payload": {
            "duration_seconds": 30,
            "aspect_ratio": "9:16",
            "title": "DIN 6 inspection proof",
            "utm": "tiktok / organic / din6-proof-demo",
        },
    }


@pytest.mark.django_db
def test_four_approved_channels_export_one_deterministic_safe_archive(growth_publish_ready):
    client, _organization, packages = growth_publish_ready
    for package in packages:
        package.payload = {
            "title": f"{package.channel} inspection proof",
            "body": "Verified gear inspection evidence.",
            "cta": "Review the capability summary",
            "language": "en",
            "landing_page_url": "https://example.com/gears",
            "hashtags": ["gears", "inspection"],
            "utm": f"utm_source={package.channel.lower()}&utm_medium=organic",
            "verified_fact_evidence": [{
                "fact_id": "11111111-1111-4111-8111-111111111111",
                "field_name": "process",
                "value": "Gear grinding",
                "source_filename": "gear-catalog.pdf",
                "source_page": 2,
                "source_excerpt": "Process: Gear grinding",
                "is_demo": True,
                "storage_key": "organizations/secret/internal",
            }],
            "asset_references": [{
                "original_filename": "../gear-photo.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": 1024,
                "checksum": "a" * 64,
                "storage_key": "organizations/secret/internal",
            }],
            "contact_email": "private@example.com",
            "api_key": "must-not-export",
        }
        if package.channel == "TIKTOK":
            package.payload.update({
                "duration_seconds": 30,
                "aspect_ratio": "9:16",
                "script": "Verified gear inspection evidence.",
                "shot_list": [{
                    "scene": "1",
                    "visual": "Gear close-up",
                    "on_screen_text": "Inspection proof",
                }],
                "voiceover": "Verified gear inspection evidence.",
                "voiceover_language": "en",
                "subtitles": "Verified gear inspection evidence.",
                "subtitle_language": "en",
            })
        package.save(update_fields=["payload", "updated_at"])
    payload = {"package_ids": [str(package.id) for package in packages]}

    first = client.post(
        "/api/v1/growth/channel-packages/manual-export-all", payload, format="json",
    )
    second = client.post(
        "/api/v1/growth/channel-packages/manual-export-all", payload, format="json",
    )

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(first.content) < 2 * 1024 * 1024
    assert first["Content-Type"] == "application/zip"
    assert first["X-Content-SHA256"] == second["X-Content-SHA256"]
    assert first["ETag"] == f'"{first["X-Content-SHA256"]}"'
    assert hashlib.sha256(first.content).hexdigest() == hashlib.sha256(second.content).hexdigest()
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "facebook/assets.json", "facebook/content.json", "facebook/evidence.json",
            "instagram/assets.json", "instagram/content.json", "instagram/evidence.json",
            "linkedin/assets.json", "linkedin/content.json", "linkedin/evidence.json",
            "tiktok/assets.json", "tiktok/content.json", "tiktok/evidence.json",
        ]
        manifest = json.loads(archive.read("manifest.json"))
        content = json.loads(archive.read("tiktok/content.json"))
        evidence = json.loads(archive.read("tiktok/evidence.json"))
        assets = json.loads(archive.read("tiktok/assets.json"))
    assert manifest["content_hash"] == first["X-Content-SHA256"]
    assert manifest["delivery"] == "MANUAL_ONLY"
    assert manifest["channels"] == ["FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK"]
    assert content["aspect_ratio"] == "9:16"
    assert content["language"] == "en"
    assert content["landing_page_url"] == "https://example.com/gears"
    assert content["voiceover"] == "Verified gear inspection evidence."
    assert content["subtitles"] == "Verified gear inspection evidence."
    assert content["shot_list"] == [{
        "scene": "1", "visual": "Gear close-up", "on_screen_text": "Inspection proof",
    }]
    assert "english_voiceover" not in content
    assert "chinese_subtitles" not in content
    assert content["tags"] == ["gears", "inspection"]
    assert evidence[0]["source_filename"] == "gear-catalog.pdf"
    assert assets == [{
        "checksum": "a" * 64,
        "mime_type": "image/jpeg",
        "original_filename": "gear-photo.jpg",
        "size_bytes": 1024,
    }]
    serialized = first.content
    assert b"organizations/secret/internal" not in serialized
    assert b"private@example.com" not in serialized
    assert b"must-not-export" not in serialized


@pytest.mark.django_db
def test_combined_manual_export_rejects_unapproved_missing_and_foreign_packages(
    growth_publish_ready,
):
    client, organization, packages = growth_publish_ready
    endpoint = "/api/v1/growth/channel-packages/manual-export-all"
    package_ids = [str(package.id) for package in packages]
    packages[0].status = "AWAITING_REVIEW"
    packages[0].save(update_fields=["status", "updated_at"])

    unapproved = client.post(endpoint, {"package_ids": package_ids}, format="json")
    missing = client.post(endpoint, {"package_ids": package_ids[:3]}, format="json")

    foreign = Organization.objects.create(name="Foreign Export", slug="foreign-export")
    packages[0].status = "APPROVED"
    packages[0].organization = foreign
    packages[0].save(update_fields=["organization", "status", "updated_at"])
    hidden = client.post(endpoint, {"package_ids": package_ids}, format="json")

    read_only_role = Role.objects.create_read_only()
    read_only_user = get_user_model().objects.create_user(username="export-read-only")
    Membership.objects.create(
        user=read_only_user, organization=organization, role=read_only_role,
    )
    read_only_client = APIClient()
    read_only_client.force_authenticate(user=read_only_user)
    forbidden = read_only_client.post(endpoint, {"package_ids": package_ids}, format="json")

    assert unapproved.status_code == missing.status_code == hidden.status_code == 409
    assert forbidden.status_code == 403
    assert unapproved.data["code"] == "MANUAL_EXPORT_NOT_READY"
    assert missing.data["code"] == "MANUAL_EXPORT_NOT_READY"
    assert hidden.data["code"] == "MANUAL_EXPORT_NOT_READY"
    assert "Foreign Export" not in str(hidden.data)
    assert packages[1].organization_id == organization.id


@pytest.mark.django_db
def test_invalid_tiktok_manual_package_returns_recoverable_conflict(growth_client):
    client, organization = growth_client
    from apps.growth.models import ChannelPackage

    package = ChannelPackage.objects.create(
        organization=organization,
        channel="TIKTOK",
        payload={"title": "Incomplete reviewed video"},
        status="APPROVED",
        is_demo=True,
    )

    response = client.post(
        f"/api/v1/growth/channel-packages/{package.id}/manual-export", {}, format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "PACKAGE_FORMAT_INVALID"


@pytest.mark.django_db
def test_company_fact_can_be_human_verified_and_foreign_fact_is_hidden(growth_client):
    client, organization = growth_client
    from apps.growth.models import FieldProvenance

    fact = FieldProvenance.objects.create(
        organization=organization,
        field_name="accuracy_grade",
        field_value="DIN 6",
        source_label="Product library",
        verification_status="NEEDS_EVIDENCE",
        source_cost_micros=20000,
    )
    foreign = Organization.objects.create(name="Foreign", slug="foreign-facts")
    foreign_fact = FieldProvenance.objects.create(
        organization=foreign,
        field_name="secret_capacity",
        field_value="hidden",
        source_label="private",
        verification_status="NEEDS_CONFIRMATION",
    )

    verified = client.post(f"/api/v1/growth/company-facts/{fact.id}/verify", {}, format="json")
    hidden = client.post(
        f"/api/v1/growth/company-facts/{foreign_fact.id}/verify", {}, format="json",
    )

    assert verified.status_code == 200
    assert verified.data["verification_status"] == "VERIFIED"
    fact.refresh_from_db()
    assert fact.verification_status == "VERIFIED"
    assert hidden.status_code == 404
    assert "hidden" not in hidden.content.decode()
