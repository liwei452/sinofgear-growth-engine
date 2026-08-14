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
    return client, organization, packages


@pytest.mark.django_db
def test_workspace_route_exposes_four_separate_collections(growth_client):
    client, _organization = growth_client

    response = client.get("/api/v1/growth/workspace")

    assert response.status_code == 200
    assert set(response.data) >= {
        "target_accounts", "contacts", "intent_signals", "inbound_leads", "follow_ups",
        "outreach_drafts", "channel_packages", "metric_receipts", "field_provenance",
        "connectors",
    }
    assert response.data["connectors"] == [
        {
            "channel": channel,
            "status": "NOT_CONNECTED",
            "connection_label": "未连接",
            "recovery_action": "连接账号",
            "mode": "",
        }
        for channel in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK")
    ]


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
    assert first.data["status"] == "PARTIAL_SUCCESS"
    assert first.data["is_demo"] is True
    assert first.data["data_label"] == "Demo / Fake 发布结果"
    assert {item["channel"] for item in first.data["items"]} == {
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK",
    }
    assert next(item for item in first.data["items"] if item["channel"] == "TIKTOK")["error_code"] == "PROVIDER_ERROR"

    retried = client.post(
        f"/api/v1/growth/publish-batches/{first.data['id']}/retry-failed", {}, format="json",
    )
    detail = client.get(f"/api/v1/growth/publish-batches/{first.data['id']}")
    workspace = client.get("/api/v1/growth/workspace")

    assert retried.status_code == 200
    assert retried.data["status"] == "SUCCEEDED"
    assert detail.data == retried.data
    assert workspace.data["publish_batches"][0] == retried.data
    attempts = {item["channel"]: item["attempt_number"] for item in retried.data["items"]}
    assert attempts == {"FACEBOOK": 1, "INSTAGRAM": 1, "LINKEDIN": 1, "TIKTOK": 2}
    assert all(
        item["external_post_url"].startswith("https://example.invalid/demo-post/")
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
def test_workspace_keeps_growth_objects_distinct_and_organization_scoped(growth_client):
    client, organization = growth_client
    from apps.growth.models import Contact, InboundLead, IntentSignal, TargetAccount

    account = TargetAccount.objects.create(
        organization=organization, name="PackTech GmbH", country="Germany",
        industry="Packaging machinery", employee_range="51-200", is_demo=True,
    )
    Contact.objects.create(
        organization=organization, account=account, full_name="Purchasing team",
        role_title="Public contact path", public_contact_path="https://packtech.example/contact",
    )
    IntentSignal.objects.create(
        organization=organization, account=account, signal_type="HIRING",
        source_label="Public careers page", source_url="https://packtech.example/careers",
        evidence_text="Hiring a precision transmission buyer", confidence=88, is_demo=True,
    )
    InboundLead.objects.create(
        organization=organization, account=account, source_label="Demo website form", is_demo=True,
    )
    foreign = Organization.objects.create(name="Foreign", slug="foreign-growth")
    TargetAccount.objects.create(organization=foreign, name="Foreign secret", country="US")

    response = client.get("/api/v1/growth/workspace")

    assert response.status_code == 200
    assert [item["name"] for item in response.data["target_accounts"]] == ["PackTech GmbH"]
    assert len(response.data["contacts"]) == 1
    assert len(response.data["intent_signals"]) == 1
    assert len(response.data["inbound_leads"]) == 1
    assert response.data["target_accounts"][0]["data_label"] == "Demo / Fake"
    assert "Foreign secret" not in str(response.data)


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
def test_workspace_returns_persisted_follow_up_and_latest_draft(growth_client):
    client, organization = growth_client
    from apps.growth.models import TargetAccount

    account = TargetAccount.objects.create(
        organization=organization, name="PackTech GmbH", country="Germany", is_demo=True,
    )
    client.post(f"/api/v1/growth/opportunities/{account.id}/follow-up", {}, format="json")
    draft = client.post(f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json")

    response = client.get("/api/v1/growth/workspace")

    assert response.status_code == 200
    assert str(response.data["follow_ups"][0]["account_id"]) == str(account.id)
    assert response.data["outreach_drafts"][0]["id"] == str(draft.data["id"])
    assert response.data["outreach_drafts"][0]["delivery"] == "NEVER_SENT"


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
