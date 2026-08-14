import pytest
from django.contrib.auth import get_user_model

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


def test_one_click_publishes_eligible_channels_and_is_idempotent(publish_context):
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
    assert first.status == GrowthPublishBatch.Status.PARTIAL_SUCCESS
    succeeded = first.items.exclude(status=GrowthPublishItem.Status.FAILED)
    assert succeeded.count() == 3
    assert all(item.external_post_url.startswith("https://example.invalid/demo-post/") for item in succeeded)
    assert first.items.get(channel="TIKTOK").last_error["code"] == "PROVIDER_ERROR"


def test_retry_reexecutes_only_failed_channels(publish_context):
    organization, user, packages, _accounts = publish_context
    batch = create_publish_batch(
        organization=organization,
        actor=user,
        package_ids=[package.id for package in packages],
        idempotency_key="publish-demo-retry",
    )
    original_successes = {
        item.channel: (item.attempt_number, item.external_post_id)
        for item in batch.items.filter(status=GrowthPublishItem.Status.SUCCEEDED)
    }

    retried = retry_failed_items(batch=batch, actor=user)

    assert retried.status == GrowthPublishBatch.Status.SUCCEEDED
    assert retried.items.get(channel="TIKTOK").attempt_number == 2
    assert retried.items.get(channel="TIKTOK").status == GrowthPublishItem.Status.SUCCEEDED
    for channel, expected in original_successes.items():
        item = retried.items.get(channel=channel)
        assert (item.attempt_number, item.external_post_id) == expected


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
