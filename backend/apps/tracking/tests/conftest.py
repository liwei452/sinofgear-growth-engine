import pytest

from apps.publishing.tests.conftest import publishing_context as _base_publishing_context
from apps.publishing.services import create_publish_task, execute_publish_task


publishing_context = pytest.fixture(name="publishing_context")(_base_publishing_context.__wrapped__)



@pytest.fixture
def tracking_context(publishing_context):
    context = publishing_context
    task = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="tracking-published-post", actor=context["actor"],
    )
    post = execute_publish_task(task.id)
    context["content"].refresh_from_db()
    return {**context, "published_post": post}
