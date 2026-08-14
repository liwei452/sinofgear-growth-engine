import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.growth.models import (
    ChannelPackage,
    GrowthPublishBatch,
    GrowthPublishItem,
)
from apps.identity.models import Organization


@pytest.fixture
def publishing_rows(db):
    organization = Organization.objects.create(name="Publishing models", slug="publishing-models")
    user = get_user_model().objects.create_user(username="publishing-model-owner")
    package = ChannelPackage.objects.create(
        organization=organization,
        channel="LINKEDIN",
        payload={"title": "Inspection proof"},
        status="APPROVED",
        is_demo=True,
    )
    return organization, user, package


def test_publish_batch_enforces_idempotency_per_organization(publishing_rows):
    organization, user, _package = publishing_rows
    GrowthPublishBatch.objects.create(
        organization=organization,
        created_by=user,
        idempotency_key="homepage-proof-1",
        request_fingerprint="a" * 64,
        status=GrowthPublishBatch.Status.QUEUED,
        is_demo=True,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        GrowthPublishBatch.objects.create(
            organization=organization,
            created_by=user,
            idempotency_key="homepage-proof-1",
            request_fingerprint="b" * 64,
            status=GrowthPublishBatch.Status.QUEUED,
            is_demo=True,
        )


def test_publish_items_preserve_one_channel_snapshot_per_batch(publishing_rows):
    organization, user, package = publishing_rows
    batch = GrowthPublishBatch.objects.create(
        organization=organization,
        created_by=user,
        idempotency_key="homepage-proof-2",
        request_fingerprint="c" * 64,
        status=GrowthPublishBatch.Status.QUEUED,
        is_demo=True,
    )
    item = GrowthPublishItem.objects.create(
        organization=organization,
        batch=batch,
        channel_package=package,
        channel="LINKEDIN",
        payload_snapshot={"title": "Inspection proof"},
        status=GrowthPublishItem.Status.QUEUED,
    )

    assert item.payload_snapshot == {"title": "Inspection proof"}
    assert set(GrowthPublishBatch.Status.values) == {
        "QUEUED", "RUNNING", "PARTIAL_SUCCESS", "SUCCEEDED", "FAILED",
        "CONFIGURATION_REQUIRED",
    }
    assert set(GrowthPublishItem.Status.values) == {
        "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED",
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        GrowthPublishItem.objects.create(
            organization=organization,
            batch=batch,
            channel_package=package,
            channel="LINKEDIN",
            payload_snapshot={},
            status=GrowthPublishItem.Status.QUEUED,
        )


def test_publish_history_cannot_be_deleted(publishing_rows):
    organization, user, package = publishing_rows
    batch = GrowthPublishBatch.objects.create(
        organization=organization,
        created_by=user,
        idempotency_key="homepage-proof-3",
        request_fingerprint="d" * 64,
        status=GrowthPublishBatch.Status.QUEUED,
        is_demo=True,
    )
    item = GrowthPublishItem.objects.create(
        organization=organization,
        batch=batch,
        channel_package=package,
        channel="LINKEDIN",
        payload_snapshot={},
        status=GrowthPublishItem.Status.SKIPPED,
    )

    with pytest.raises(ValueError, match="history cannot be deleted"):
        item.delete()
    with pytest.raises(ValueError, match="history cannot be deleted"):
        batch.delete()
