import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.growth.models import ChannelPackage, GrowthPublishBatch, GrowthPublishItem
from apps.growth.publishing import (
    PublishBatchConflict,
    PublishPackageSelectionInvalid,
    create_publish_batch,
    retry_failed_items,
)
from apps.identity.models import Organization
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount
from integrations.platforms.base import OfficialPublishResult
from integrations.platforms.registry import ConnectorRegistry


CHANNELS = ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK")


@pytest.fixture
def publish_context(db):
    organization = Organization.objects.create(name="Publishing demo", slug="publishing-demo")
    user = get_user_model().objects.create_user(username="publishing-demo-owner")
    packages = []
    accounts = {}
    for index, channel in enumerate(CHANNELS, start=1):
        platform = Platform.objects.create(code=channel, name=channel.title())
        credential = ConnectorCredential.objects.create(
            organization=organization,
            platform=platform,
            secret_reference=f"test-only://{channel.lower()}",
            granted_scopes=[AccountCapability.PUBLISH],
        )
        accounts[channel] = SocialAccount.objects.create(
            organization=organization,
            platform=platform,
            credential=credential,
            external_id=f"demo-{index}",
            display_name=f"{channel.title()} Demo",
            publish_mode=SocialAccount.PublishMode.API_AUTO,
            connector_metadata={
                "connection_kind": "demo_fake",
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
    return organization, user, packages, accounts


def test_one_click_demo_packages_are_truthfully_skipped_and_idempotent(publish_context):
    organization, user, packages, _accounts = publish_context

    first = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id for package in packages],
        idempotency_key="publish-demo-1",
    )
    second = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id for package in reversed(packages)],
        idempotency_key="publish-demo-1",
    )

    assert first.id == second.id
    assert first.items.count() == 4
    assert set(first.items.values_list("channel", flat=True)) == set(CHANNELS)
    assert first.status == GrowthPublishBatch.Status.CONFIGURATION_REQUIRED
    assert all(
        item.status == GrowthPublishItem.Status.SKIPPED for item in first.items.all()
    )
    assert all(
        item.last_error["code"] == "DEMO_ONLY_NO_EXTERNAL_PUBLISH"
        for item in first.items.all()
    )


def test_retry_does_not_reexecute_demo_skipped_channels(publish_context):
    organization, user, packages, _accounts = publish_context
    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id for package in packages],
        idempotency_key="publish-demo-retry",
    )
    original = {item.channel: item.attempt_number for item in batch.items.all()}

    retried = retry_failed_items(batch=batch, actor=user)

    assert retried.status == GrowthPublishBatch.Status.CONFIGURATION_REQUIRED
    for channel, expected in original.items():
        item = retried.items.get(channel=channel)
        assert item.attempt_number == expected
        assert item.status == GrowthPublishItem.Status.SKIPPED


def test_unapproved_and_unconnected_channels_are_explicitly_skipped(publish_context):
    organization, user, packages, accounts = publish_context
    packages[0].status = "AWAITING_REVIEW"
    packages[0].save(update_fields=["status"])
    accounts["FACEBOOK"].delete()

    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[packages[0].id, packages[1].id],
        idempotency_key="publish-demo-skips",
    )

    assert batch.status == GrowthPublishBatch.Status.CONFIGURATION_REQUIRED
    assert batch.items.get(channel="LINKEDIN").last_error["code"] == "CONTENT_NOT_APPROVED"
    assert batch.items.get(channel="FACEBOOK").last_error["code"] == "ACCOUNT_NOT_CONNECTED"


def test_batch_rejects_foreign_packages_without_creating_history(publish_context):
    organization, user, _packages, _accounts = publish_context
    foreign = Organization.objects.create(name="Foreign", slug="foreign-publish")
    foreign_package = ChannelPackage.objects.create(
        organization=foreign,
        channel="LINKEDIN",
        payload={"title": "secret"},
        status="APPROVED",
        is_demo=True,
    )

    with pytest.raises(PublishPackageSelectionInvalid):
        create_publish_batch(
            organization=organization,
            actor=user,
            package_ids=[foreign_package.id],
            idempotency_key="publish-foreign",
        )

    assert not GrowthPublishBatch.objects.filter(organization=organization).exists()


def test_idempotency_key_cannot_be_reused_for_different_packages(publish_context):
    organization, user, packages, _accounts = publish_context
    create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[packages[0].id],
        idempotency_key="publish-conflict",
    )

    with pytest.raises(PublishBatchConflict):
        create_publish_batch(
            organization=organization,
            actor=user,
            package_ids=[packages[1].id],
            idempotency_key="publish-conflict",
        )


class OfficialSuccessConnector:
    def __init__(self):
        self.requests = []

    def publish(self, request):
        self.requests.append(request)
        return OfficialPublishResult(
            status="SUCCEEDED",
            external_id="official-post-1",
            external_url="https://social.example.com/official-post-1",
        )


def test_official_account_uses_registry_and_never_calls_fake(monkeypatch, db):
    organization = Organization.objects.create(name="Official", slug="official-publish")
    user = get_user_model().objects.create_user(username="official-owner")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://linkedin/official",
        granted_scopes=[AccountCapability.PUBLISH],
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="5515715",
        display_name="Official LinkedIn",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )
    package = ChannelPackage.objects.create(
        organization=organization,
        channel="LINKEDIN",
        payload={"commentary": "Reviewed proof"},
        status="APPROVED",
        is_demo=False,
    )
    connector = OfficialSuccessConnector()
    monkeypatch.setattr(
        "apps.growth.publishing.get_connector_registry",
        lambda: ConnectorRegistry(official_connectors={"LINKEDIN": connector}),
    )

    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id],
        idempotency_key="official-linkedin-1",
    )

    item = batch.items.get()
    assert batch.is_demo is False
    assert item.status == GrowthPublishItem.Status.SUCCEEDED
    assert item.external_post_id == "official-post-1"
    assert connector.requests[0].credential_reference == "vault://linkedin/official"
    assert connector.requests[0].idempotency_key == "official-linkedin-1:LINKEDIN"


def test_official_connector_configuration_failure_does_not_fall_back_to_fake(monkeypatch, db):
    organization = Organization.objects.create(name="Unconfigured", slug="official-unconfigured")
    user = get_user_model().objects.create_user(username="unconfigured-owner")
    platform = Platform.objects.create(code="TIKTOK", name="TikTok")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://tiktok/unconfigured",
        granted_scopes=[AccountCapability.PUBLISH],
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="creator-1",
        display_name="TikTok",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )
    package = ChannelPackage.objects.create(
        organization=organization,
        channel="TIKTOK",
        payload={"video_url": "https://cdn.example.com/video.mp4"},
        status="APPROVED",
        is_demo=False,
    )
    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id],
        idempotency_key="official-unconfigured-1",
    )

    item = batch.items.get()
    assert item.status == GrowthPublishItem.Status.FAILED
    assert item.last_error == {
        "code": "CONFIGURATION_REQUIRED",
        "message": "Official publishing connector is not configured.",
        "retryable": False,
        "retry_after_seconds": None,
    }


def test_expired_official_authorization_is_not_retried(db):
    organization = Organization.objects.create(name="Expired", slug="official-expired")
    user = get_user_model().objects.create_user(username="expired-owner")
    platform = Platform.objects.create(code="FACEBOOK", name="Facebook")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://facebook/expired",
        granted_scopes=[AccountCapability.PUBLISH],
        expires_at=timezone.now(),
    )
    SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="page-1",
        display_name="Facebook",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
        connector_metadata={"connection_kind": "official_oauth"},
    )
    package = ChannelPackage.objects.create(
        organization=organization,
        channel="FACEBOOK",
        payload={"message": "Reviewed"},
        status="APPROVED",
        is_demo=False,
    )

    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id],
        idempotency_key="official-expired-1",
    )
    before = batch.items.get().attempt_number
    retried = retry_failed_items(batch=batch, actor=user)

    item = retried.items.get()
    assert item.last_error["code"] == "REAUTHORIZATION_REQUIRED"
    assert item.attempt_number == before
