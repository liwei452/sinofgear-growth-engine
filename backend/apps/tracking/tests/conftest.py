import pytest
from django.utils import timezone

from apps.publishing.models import PublishAttempt, PublishedPost, PublishTask, publishing_writes
from apps.publishing.tests.conftest import publishing_context as _base_publishing_context


publishing_context = pytest.fixture(name="publishing_context")(_base_publishing_context.__wrapped__)



@pytest.fixture
def tracking_context(publishing_context):
    context = publishing_context
    with publishing_writes():
        task = PublishTask.objects.create(
            organization=context["organization"],
            platform_content=context["content"],
            content_version=context["content"].version,
            social_account=context["account"],
            platform=context["platform"],
            connector_code="mock",
            idempotency_key="tracking-published-post",
            request_fingerprint="a" * 64,
            status=PublishTask.Status.SUCCEEDED,
            attempt_number=1,
            created_by=context["actor"],
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        attempt = PublishAttempt.objects.create(
            organization=context["organization"],
            task=task,
            number=1,
            status=PublishAttempt.Status.SUCCEEDED,
            request_fingerprint="a" * 64,
            external_id="post-1",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
        post = PublishedPost.objects.create(
            organization=context["organization"],
            task=task,
            attempt=attempt,
            platform_content=context["content"],
            social_account=context["account"],
            external_id="post-1",
            published_at=timezone.now(),
        )
    return {**context, "published_post": post}
