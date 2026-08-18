from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.campaigns.models import Campaign
from apps.catalog.models import Product
from apps.growth.mission_services import (
    link_mission_entity,
    sync_mission_links_from_agent_run,
)
from apps.growth.models import (
    AgentRun,
    AgentRunStep,
    ChannelPackage,
    FollowUp,
    GrowthMission,
    GrowthPublishItem,
    MissionEntityLink,
    OutreachDraft,
    OutreachMessage,
    TargetAccount,
)
from apps.growth.outreach_events import record_sent
from apps.growth.publishing import create_publish_batch
from apps.growth.work_items import project_work_items
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Links Org", slug="links-org")


@pytest.fixture
def operator(db):
    return get_user_model().objects.create_user(username="links-operator", password="x")


@pytest.fixture
def product(db, organization):
    return Product.objects.create(
        organization=organization,
        name_en="Helical Gear",
        module_min=1,
        module_max=2,
        tooth_count_min=10,
        tooth_count_max=20,
        pressure_angle=20,
        moq=1,
        status=Product.Status.ACTIVE,
        manufacturing_capabilities=["Hobbing"],
        inspection_capabilities=["CMM"],
    )


@pytest.fixture
def mission(db, organization, operator, product):
    return GrowthMission.objects.create(
        organization=organization,
        title="Links mission",
        objective="Get replies",
        target_countries=["ZA"],
        target_industries=["mining"],
        primary_product=product,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 20),
        allowed_channels=["EMAIL", "LINKEDIN"],
        attribution_code="gm-links",
        created_by=operator,
    )


@pytest.fixture
def account(db, organization):
    return TargetAccount.objects.create(organization=organization, name="Acme", country="ZA")


@pytest.fixture
def draft(db, organization, account):
    return OutreachDraft.objects.create(
        organization=organization,
        account=account,
        english_draft="Hello",
        chinese_explanation="test",
    )


def _waiting_run(organization, *, tool_name, output):
    run = AgentRun.objects.create(
        organization=organization,
        idempotency_key=f"run-{tool_name}-{output.get('seed', '')}",
        goal="test",
        agent_type="proactive" if tool_name == "send_email" else "content_strategy",
        status=AgentRun.Status.WAITING_APPROVAL,
    )
    AgentRunStep.objects.create(
        organization=organization,
        run=run,
        index=0,
        tool_name=tool_name,
        args={},
        outcome="blocked_approval",
        output=output,
        approval_token="token",
    )
    return run


def test_waiting_send_approval_projects_one_outreach_work_item(
    mission, operator, monkeypatch
):
    from apps.growth import work_items as wi

    monkeypatch.setattr(wi, "email_delivery_readiness", lambda: "CONNECTED")
    run = _waiting_run(mission.organization, tool_name="send_email", output={"english_draft": "Hi"})
    link_mission_entity(
        mission=mission,
        entity=run,
        lane=MissionEntityLink.Lane.OUTREACH,
        actor=operator,
    )
    items = project_work_items(organization=mission.organization, mission=mission)
    item = next(row for row in items if row.kind == "OUTREACH_REVIEW")
    assert item.action_type == "APPROVE_AGENT_RUN"
    assert item.source_id == str(run.id)
    assert item.mission_id == str(mission.id)


def test_approved_channel_package_disappears_from_review_projection(
    mission, operator
):
    package = ChannelPackage.objects.create(
        organization=mission.organization,
        channel="LINKEDIN",
        payload={"title": "post"},
        status="AWAITING_REVIEW",
        is_demo=False,
    )
    link_mission_entity(mission=mission, entity=package, lane="SOCIAL", actor=operator)
    assert any(
        row.kind == "SOCIAL_REVIEW"
        for row in project_work_items(organization=mission.organization)
    )
    package.status = "APPROVED"
    package.save(update_fields=["status", "updated_at"])
    assert not any(
        row.source_id == str(package.id)
        for row in project_work_items(organization=mission.organization)
    )


def test_agent_outputs_are_linked_back_to_the_same_mission(mission, operator):
    campaign = Campaign.objects.create(
        organization=mission.organization,
        name="Linked campaign",
    )
    run = AgentRun.objects.create(
        organization=mission.organization,
        idempotency_key="content-run",
        goal="content",
        agent_type="content_strategy",
        status=AgentRun.Status.COMPLETED,
    )
    AgentRunStep.objects.create(
        organization=mission.organization,
        run=run,
        index=0,
        tool_name="create_content_brief",
        args={},
        outcome="succeeded",
        output={"campaign_id": str(campaign.id)},
    )
    link_mission_entity(mission=mission, entity=run, lane="SOCIAL", actor=operator)
    sync_mission_links_from_agent_run(run=run, actor=operator)
    assert MissionEntityLink.objects.filter(
        mission=mission,
        entity_type=MissionEntityLink.EntityType.CAMPAIGN,
        lane=MissionEntityLink.Lane.SOCIAL,
    ).exists()


def test_default_mock_email_provider_cannot_create_a_sent_message(
    account, draft
):
    from apps.growth.email_delivery import EmailDeliveryUnavailable

    FollowUp.objects.create(organization=account.organization, account=account)
    with pytest.raises(EmailDeliveryUnavailable, match="not connected"):
        record_sent(account=account, draft=draft, email="buyer@example.com")
    assert not OutreachMessage.objects.filter(account=account).exists()
    assert account.follow_ups.get().stage != FollowUp.Stage.EMAIL_1_SENT


def test_demo_fake_connector_cannot_create_formal_publish_success(
    mission, operator
):
    from apps.platforms.models import ConnectorCredential, Platform, SocialAccount

    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=mission.organization,
        platform=platform,
        secret_reference="vault://demo",
        granted_scopes=["PUBLISH"],
    )
    SocialAccount.objects.create(
        organization=mission.organization,
        platform=platform,
        credential=credential,
        external_id="demo",
        display_name="Demo",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "demo_fake", "fixture": "phase-a-e2e"},
    )
    package = ChannelPackage.objects.create(
        organization=mission.organization,
        channel="LINKEDIN",
        payload={"title": "demo"},
        status="APPROVED",
        is_demo=True,
    )
    batch = create_publish_batch(
        organization=mission.organization,
        actor=operator,
        package_ids=[package.id],
        idempotency_key="demo-no-formal-publish",
    )
    assert batch.status == "CONFIGURATION_REQUIRED"
    assert not batch.items.filter(status=GrowthPublishItem.Status.SUCCEEDED).exists()
