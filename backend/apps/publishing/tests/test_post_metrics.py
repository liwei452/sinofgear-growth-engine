from apps.publishing.metrics import sync_post_metrics
from apps.publishing.models import PostMetric
from apps.publishing.services import create_publish_task, execute_publish_task


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
