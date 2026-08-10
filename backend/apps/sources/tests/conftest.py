import uuid

import pytest
from django.contrib.auth import get_user_model

from apps.assets.models import MaterialAsset
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.sources.models import MonitoringTarget, SourceContent, SourceSignal


@pytest.fixture
def organization():
    return Organization.objects.create(name="Source Own", slug="source-own")


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Source Other", slug="source-other")


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="source-user")


@pytest.fixture
def target(organization, user):
    return MonitoringTarget.objects.create(
        organization=organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.MANUAL_URL,
        platform="MANUAL",
        normalized_url="https://Example.com:443/posts/42#discussion",
        label="Gear request",
        created_by=user,
    )


@pytest.fixture
def content(target, user):
    return SourceContent.objects.create(
        organization=target.organization,
        monitoring_target=target,
        platform="MANUAL",
        external_id="post-42",
        canonical_url="https://example.com/posts/42",
        original_text="We need 200 replacement helical gears.",
        content_hash="a" * 64,
        created_by=user,
    )


@pytest.fixture
def signal(target, content, user):
    return SourceSignal.objects.create(
        organization=target.organization,
        monitoring_target=target,
        source_content=content,
        signal_type=SourceSignal.SignalType.COMMENT,
        platform="MANUAL",
        external_id="comment-7",
        created_by=user,
    )


def make_asset(*, organization, user, marker: str) -> MaterialAsset:
    asset_id = uuid.uuid4()
    return MaterialAsset.objects.create(
        id=asset_id,
        organization=organization,
        asset_type=MaterialAsset.AssetType.IMAGE,
        storage_key=f"organizations/{organization.id}/assets/{asset_id}/original",
        original_filename=f"{marker}.png",
        mime_type="image/png",
        size_bytes=1,
        checksum=(marker.encode().hex() + "0" * 64)[:64],
        created_by=user,
    )


@pytest.fixture
def asset(organization, user):
    return make_asset(organization=organization, user=user, marker="11")


@pytest.fixture
def other_asset(other_organization, user):
    return make_asset(organization=other_organization, user=user, marker="22")


@pytest.fixture
def job(organization, user):
    return JobService.create(
        organization=organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"source": "manual"},
        idempotency_key="source-batch-job",
        created_by=user,
    )
