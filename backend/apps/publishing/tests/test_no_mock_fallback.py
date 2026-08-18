from apps.publishing.models import PublishTask, PublishedPost
from apps.publishing.services import create_publish_task, execute_publish_task


def test_non_oauth_account_fails_instead_of_mock_publishing(
    publishing_context, settings,
):
    settings.PUBLISHING_MOCK_ENABLED = False
    context = publishing_context

    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key="no-mock-fallback",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    task.refresh_from_db()
    assert result is None
    assert task.status == PublishTask.Status.FAILED
    assert task.last_error["code"] == "PUBLISH_NOT_ELIGIBLE"
    assert not PublishedPost.objects.filter(task=task).exists()


def test_demo_fake_account_still_publishes_through_mock(
    publishing_context, settings,
):
    settings.PUBLISHING_MOCK_ENABLED = False
    context = publishing_context
    account = context["account"]
    account.connector_metadata = {"fixture": "phase-a-e2e"}
    account.save(update_fields=["connector_metadata", "updated_at"])

    task = create_publish_task(
        content=context["content"],
        account=account,
        idempotency_key="demo-fake-account",
        actor=context["actor"],
    )

    result = execute_publish_task(task.id)

    task.refresh_from_db()
    assert result is not None
    assert task.status == PublishTask.Status.SUCCEEDED
    assert PublishedPost.objects.filter(task=task).exists()
