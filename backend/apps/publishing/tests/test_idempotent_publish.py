import pytest
from datetime import timedelta
from django.utils import timezone

from apps.publishing.models import PublishTask
from apps.publishing.services import PublishingConflict, create_publish_task


def test_same_idempotency_key_and_request_returns_original_task(publishing_context):
    context = publishing_context
    scheduled_at = timezone.now() + timedelta(hours=1)
    first = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="same-key", scheduled_at=scheduled_at, actor=context["actor"],
    )
    second = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="same-key", scheduled_at=scheduled_at, actor=context["actor"],
    )

    assert second.pk == first.pk


def test_same_idempotency_key_with_different_request_conflicts(publishing_context):
    context = publishing_context
    scheduled_at = timezone.now() + timedelta(hours=1)
    create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="same-key", scheduled_at=scheduled_at, actor=context["actor"],
    )

    with pytest.raises(PublishingConflict, match="different request"):
        create_publish_task(
            content=context["content"], account=context["account"],
            idempotency_key="same-key", timezone_name="Asia/Shanghai",
            scheduled_at=scheduled_at,
            actor=context["actor"],
        )


def test_unique_constraint_race_recovers_the_committed_original(
    publishing_context, monkeypatch,
):
    context = publishing_context
    original = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="racing-key", scheduled_at=timezone.now() + timedelta(hours=1),
        actor=context["actor"],
    )
    manager = PublishTask.objects
    original_filter = manager.filter
    hidden_once = False

    def hide_initial_lookup(*args, **kwargs):
        nonlocal hidden_once
        if not hidden_once and kwargs.get("idempotency_key") == "racing-key":
            hidden_once = True
            return original_filter(pk=None)
        return original_filter(*args, **kwargs)

    monkeypatch.setattr(manager, "filter", hide_initial_lookup)

    recovered = create_publish_task(
        content=context["content"], account=context["account"],
        idempotency_key="racing-key", scheduled_at=original.scheduled_at,
        actor=context["actor"],
    )

    assert recovered.pk == original.pk
