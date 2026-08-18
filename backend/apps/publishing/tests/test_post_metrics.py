import uuid

import pytest
from django.utils import timezone

from apps.publishing.metrics import sync_post_metrics
from apps.publishing.models import (
    PostMetric,
    PublishAttempt,
    PublishedPost,
    PublishTask,
    publishing_writes,
)
from apps.publishing.services import (
    PublishingConflict,
    create_publish_task,
    execute_publish_task,
)


def test_sync_post_metrics_creates_and_updates_daily_metrics(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="metrics-1",
        actor=context["actor"],
    )
    post = execute_publish_task(task.id)
    assert post is not None

    assert sync_post_metrics(organization=context["organization"]) == 1
    metric = PostMetric.objects.get(post=post)
    assert metric.impressions > 0
    assert metric.source == "demo"

    assert sync_post_metrics(organization=context["organization"]) == 0
    assert PostMetric.objects.filter(post=post).count() == 1


def test_daily_publish_limit_blocks_extra_scheduling(publishing_context):
    context = publishing_context
    context["organization"].daily_publish_limit = 1
    context["organization"].save(update_fields=["daily_publish_limit"])

    with publishing_writes():
        task = PublishTask.objects.create(
            organization=context["organization"],
            platform_content=context["content"],
            content_version=context["content"].version,
            social_account=context["account"],
            platform=context["platform"],
            connector_code="mock",
            idempotency_key="limit-existing",
            request_fingerprint="a" * 64,
            status=PublishTask.Status.SUCCEEDED,
        )
        attempt = PublishAttempt.objects.create(
            organization=context["organization"],
            task=task,
            number=1,
            claim_token=uuid.uuid4(),
            status=PublishAttempt.Status.SUCCEEDED,
            request_fingerprint="a" * 64,
            started_at=timezone.now(),
        )
        PublishedPost.objects.create(
            organization=context["organization"],
            task=task,
            attempt=attempt,
            platform_content=context["content"],
            social_account=context["account"],
            external_id="post-limit",
            published_at=timezone.now(),
        )

    with pytest.raises(PublishingConflict, match="Daily publishing limit"):
        create_publish_task(
            content=context["content"],
            account=context["account"],
            idempotency_key="limit-2",
            actor=context["actor"],
        )
