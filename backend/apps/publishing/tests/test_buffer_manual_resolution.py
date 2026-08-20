import pytest

from apps.content.models import PlatformContent
from apps.identity.models import Organization, Role
from apps.publishing.models import (
    PublishAttempt,
    PublishedPost,
    PublishReconciliationAttempt,
    PublishTask,
)
from apps.publishing.reconciliation import reconcile_buffer_publish_task
from apps.publishing.resolution import (
    CONFIRM_NOT_PUBLISHED,
    CONFIRM_PUBLISHED,
    resolve_publish_task,
)
from apps.publishing.services import (
    PublishingConflict,
    create_publish_task,
    publish_task_is_consistent,
    retry_publish_task,
)
from integrations.platforms.buffer_types import BufferPostQueryResult

from .test_buffer_reconciliation import (
    QueryConnector,
    _observation,
    _query_runtime,
    _submitted,
)
from .test_publishing_api import _client


def _needs_attention(context, monkeypatch):
    task, account, _connection = _submitted(context, monkeypatch)
    _query_runtime(
        monkeypatch,
        QueryConnector(
            BufferPostQueryResult(
                ok=True,
                observation=_observation(status="draft", sent_at=None),
            )
        ),
    )
    reconcile_buffer_publish_task(task.id, organization=context["organization"])
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    return task, account


def test_confirm_published_is_idempotent_and_writes_one_append_only_audit(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)

    first = resolve_publish_task(
        task,
        resolution=CONFIRM_PUBLISHED,
        provider_post_id="buffer-manual-post-1",
        actor=publishing_context["actor"],
    )
    second = resolve_publish_task(
        task,
        resolution=CONFIRM_PUBLISHED,
        provider_post_id="buffer-manual-post-1",
        actor=publishing_context["actor"],
    )

    first.refresh_from_db()
    publishing_context["content"].refresh_from_db()
    assert first.id == second.id
    assert first.status == PublishTask.Status.SUCCEEDED
    assert first.provider_submission_id == "buffer-manual-post-1"
    assert publishing_context["content"].status == PlatformContent.Status.PUBLISHED
    assert PublishedPost.objects.filter(
        task=task, external_id="buffer-manual-post-1"
    ).count() == 1
    assert publish_task_is_consistent(first)
    audit = PublishReconciliationAttempt.objects.get(
        publish_task=task,
        mode=PublishReconciliationAttempt.Mode.MANUAL,
    )
    assert audit.result == PublishReconciliationAttempt.Result.SUCCEEDED
    assert audit.matched_provider_post_id == "buffer-manual-post-1"


def test_confirm_not_published_closes_old_task_and_allows_new_task(
    publishing_context, monkeypatch,
):
    task, account = _needs_attention(publishing_context, monkeypatch)

    resolved = resolve_publish_task(
        task,
        resolution=CONFIRM_NOT_PUBLISHED,
        actor=publishing_context["actor"],
    )
    replay = resolve_publish_task(
        task,
        resolution=CONFIRM_NOT_PUBLISHED,
        actor=publishing_context["actor"],
    )

    resolved.refresh_from_db()
    assert replay.id == resolved.id
    assert resolved.status == PublishTask.Status.FAILED
    assert resolved.last_error == {
        "code": "MANUALLY_CLOSED_NO_POST",
        "message": "An authorized operator confirmed that no provider post exists.",
    }
    assert not PublishedPost.objects.filter(task=task).exists()
    assert PublishReconciliationAttempt.objects.filter(
        publish_task=task,
        mode=PublishReconciliationAttempt.Mode.MANUAL,
    ).count() == 1
    assert publish_task_is_consistent(resolved)
    with pytest.raises(PublishingConflict):
        retry_publish_task(resolved)
    replacement = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="after-manual-no-post",
        actor=publishing_context["actor"],
    )
    assert replacement.id != task.id


def test_manual_resolution_rejects_invalid_or_conflicting_provider_post_id(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    for invalid in ("", "   ", "x" * 256, [], 123):
        with pytest.raises(PublishingConflict):
            resolve_publish_task(
                task,
                resolution=CONFIRM_PUBLISHED,
                provider_post_id=invalid,
                actor=publishing_context["actor"],
            )

    resolve_publish_task(
        task,
        resolution=CONFIRM_PUBLISHED,
        provider_post_id="buffer-manual-post-2",
        actor=publishing_context["actor"],
    )
    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_PUBLISHED,
            provider_post_id="different-post",
            actor=publishing_context["actor"],
        )


def test_replayed_manual_resolution_has_one_effect_even_from_stale_task_instances(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    stale_first = PublishTask.objects.get(pk=task.pk)
    stale_second = PublishTask.objects.get(pk=task.pk)

    resolve_publish_task(
        stale_first,
        resolution=CONFIRM_PUBLISHED,
        provider_post_id="buffer-concurrent-resolution",
        actor=publishing_context["actor"],
    )
    resolve_publish_task(
        stale_second,
        resolution=CONFIRM_PUBLISHED,
        provider_post_id="buffer-concurrent-resolution",
        actor=publishing_context["actor"],
    )

    assert PublishedPost.objects.filter(task=task).count() == 1
    assert PublishReconciliationAttempt.objects.filter(
        publish_task=task,
        mode=PublishReconciliationAttempt.Mode.MANUAL,
    ).count() == 1


def test_manual_resolution_api_is_manage_only_and_organization_scoped(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    path = f"/api/v1/publish-tasks/{task.id}/resolve"
    read_only = _client(
        publishing_context["organization"], Role.Code.READ_ONLY, "resolve-read"
    )
    assert read_only.post(
        path,
        {"resolution": CONFIRM_NOT_PUBLISHED},
        format="json",
    ).status_code == 403

    other = Organization.objects.create(name="Resolve Other", slug="resolve-other")
    other_client = _client(other, Role.Code.OPERATOR, "resolve-other")
    assert other_client.post(
        path,
        {"resolution": CONFIRM_NOT_PUBLISHED},
        format="json",
    ).status_code == 404

    operator = _client(
        publishing_context["organization"], Role.Code.OPERATOR, "resolve-operator"
    )
    assert operator.post(
        path,
        {"resolution": CONFIRM_PUBLISHED, "provider_post_id": 123},
        format="json",
    ).status_code == 400
    assert operator.post(
        path,
        {"resolution": CONFIRM_PUBLISHED},
        format="json",
    ).status_code == 400
    assert operator.post(
        path,
        {
            "resolution": CONFIRM_NOT_PUBLISHED,
            "provider_post_id": "not-allowed",
        },
        format="json",
    ).status_code == 400
    response = operator.post(
        path,
        {
            "resolution": CONFIRM_PUBLISHED,
            "provider_post_id": "buffer-api-manual-post",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["status"] == PublishTask.Status.SUCCEEDED
    assert response.json()["published_post"]["external_id"] == "buffer-api-manual-post"


def test_manual_resolution_service_rejects_foreign_organization(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    other = Organization.objects.create(
        name="Resolve Service Other",
        slug="resolve-service-other",
    )

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_NOT_PUBLISHED,
            actor=publishing_context["actor"],
            organization=other,
        )


def test_unknown_state_cannot_be_manually_resolved_or_normally_retried(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _submitted(publishing_context, monkeypatch)
    task.status = PublishTask.Status.SUBMISSION_UNKNOWN
    task.provider_submission_id = ""
    task.last_error = {
        "code": "OUTCOME_UNKNOWN",
        "message": "Provider outcome could not be determined.",
    }
    attempt = PublishAttempt.objects.get(task=task)
    from apps.publishing.models import publishing_writes

    with publishing_writes():
        task.save(update_fields=["status", "provider_submission_id", "last_error", "updated_at"])
        attempt.status = PublishAttempt.Status.SUBMISSION_UNKNOWN
        attempt.provider_submission_id = ""
        attempt.error = task.last_error
        attempt.outcome = "OUTCOME_UNKNOWN"
        attempt.save(update_fields=[
            "status", "provider_submission_id", "error", "outcome", "updated_at",
        ])

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_NOT_PUBLISHED,
            actor=publishing_context["actor"],
        )
    with pytest.raises(PublishingConflict):
        retry_publish_task(task)
