from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

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
from integrations.platforms.buffer_types import (
    BufferCandidateSearchResult,
    BufferPostQueryResult,
)

from .test_buffer_reconciliation import (
    CandidateConnector,
    QueryConnector,
    _candidate,
    _end_query_window,
    _observation,
    _query_runtime,
    _submitted,
    _unknown,
)
from .test_publishing_api import _client


class ManualFetchConnector:
    def __init__(self, result, *, on_fetch=None):
        self.result = result
        self.on_fetch = on_fetch
        self.fetch_requests = []
        self.publish_calls = 0

    def fetch_post(self, request):
        self.fetch_requests.append(request)
        if self.on_fetch:
            self.on_fetch()
        return self.result

    def publish(self, request):
        self.publish_calls += 1
        raise AssertionError("manual resolution must never call createPost")


def _resolution_runtime(monkeypatch, connector):
    from apps.publishing import resolution

    registry = SimpleNamespace(resolve=lambda account: connector)
    monkeypatch.setattr(
        resolution,
        "get_social_provider_runtime",
        lambda: SimpleNamespace(connector_registry=registry),
        raising=False,
    )


def _needs_attention(context, monkeypatch, *, status="draft"):
    task, account, _connection = _submitted(context, monkeypatch)
    _query_runtime(
        monkeypatch,
        QueryConnector(
            BufferPostQueryResult(
                ok=True,
                observation=_observation(status=status, sent_at=None),
            )
        ),
    )
    reconcile_buffer_publish_task(task.id, organization=context["organization"])
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    return task, account


def _no_match_attention(context, monkeypatch):
    task, account, _connection = _unknown(context, monkeypatch)
    _end_query_window(task)
    _query_runtime(
        monkeypatch,
        CandidateConnector(BufferCandidateSearchResult(ok=True, candidates=())),
    )
    from apps.publishing.reconciliation import reconcile_unknown_buffer_publish_task

    reconcile_unknown_buffer_publish_task(task.id, organization=context["organization"])
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert task.last_error["code"] == "BUFFER_RECONCILIATION_NO_MATCH"
    return task, account


def _post_not_found_attention(context, monkeypatch):
    task, account, _connection = _submitted(context, monkeypatch)
    _end_query_window(task)
    _query_runtime(
        monkeypatch,
        QueryConnector(
            BufferPostQueryResult(ok=False, error_code="BUFFER_POST_NOT_FOUND")
        ),
    )
    reconcile_buffer_publish_task(task.id, organization=context["organization"])
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    return task, account


def _sent_result(
    *, post_id="buffer-manual-post-1", channel_id="buffer-channel-1",
    service="mock", status="sent", sent_at=None,
):
    return BufferPostQueryResult(
        ok=True,
        observation=_observation(
            post_id=post_id,
            channel_id=channel_id,
            service=service,
            status=status,
            sent_at=sent_at or timezone.now().replace(microsecond=0),
        ),
    )


def test_confirm_published_is_idempotent_and_writes_one_append_only_audit(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    sent_at = timezone.now().replace(microsecond=0) - timedelta(minutes=1)
    connector = ManualFetchConnector(_sent_result(sent_at=sent_at))
    _resolution_runtime(monkeypatch, connector)

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
    assert PublishedPost.objects.get(task=task).published_at == sent_at
    assert len(connector.fetch_requests) == 1
    assert connector.publish_calls == 0
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
    task, account = _no_match_attention(publishing_context, monkeypatch)

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

    connector = ManualFetchConnector(
        _sent_result(post_id="buffer-manual-post-2")
    )
    _resolution_runtime(monkeypatch, connector)
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
    connector = ManualFetchConnector(
        _sent_result(post_id="buffer-concurrent-resolution")
    )
    _resolution_runtime(monkeypatch, connector)
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
    assert len(connector.fetch_requests) == 1
    assert connector.publish_calls == 0


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
    blocked = operator.post(
        path,
        {"resolution": CONFIRM_NOT_PUBLISHED},
        format="json",
    )
    assert blocked.status_code == 409
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    connector = ManualFetchConnector(
        _sent_result(post_id="buffer-api-manual-post")
    )
    _resolution_runtime(monkeypatch, connector)
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
    assert connector.publish_calls == 0


@pytest.mark.parametrize("provider_status", ["draft", "needs_approval", "scheduled", "sending"])
def test_nonfinal_provider_status_cannot_be_confirmed_not_published(
    publishing_context, monkeypatch, provider_status,
):
    if provider_status in {"scheduled", "sending"}:
        task, account, _connection = _submitted(publishing_context, monkeypatch)
        _query_runtime(
            monkeypatch,
            QueryConnector(BufferPostQueryResult(
                ok=True,
                observation=_observation(status=provider_status, sent_at=None),
            )),
        )
        reconcile_buffer_publish_task(task.id)
        task.refresh_from_db()
        assert task.status == PublishTask.Status.SUBMITTED
    else:
        task, account = _needs_attention(
            publishing_context, monkeypatch, status=provider_status,
        )

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_NOT_PUBLISHED,
            actor=publishing_context["actor"],
        )

    task.refresh_from_db()
    assert task.status in {
        PublishTask.Status.NEEDS_ATTENTION,
        PublishTask.Status.SUBMITTED,
    }
    with pytest.raises(PublishingConflict):
        create_publish_task(
            content=publishing_context["content"],
            account=account,
            idempotency_key=f"blocked-{provider_status}",
            actor=publishing_context["actor"],
        )


@pytest.mark.parametrize("attention_kind", ["mismatch", "ambiguous"])
def test_mismatch_or_ambiguous_attention_cannot_be_confirmed_not_published(
    publishing_context, monkeypatch, attention_kind,
):
    if attention_kind == "mismatch":
        task, account, _connection = _submitted(publishing_context, monkeypatch)
        _query_runtime(
            monkeypatch,
            QueryConnector(BufferPostQueryResult(
                ok=True,
                observation=_observation(channel_id="wrong-buffer-channel"),
            )),
        )
        reconcile_buffer_publish_task(task.id)
    else:
        task, account, _connection = _unknown(publishing_context, monkeypatch)
        _query_runtime(
            monkeypatch,
            CandidateConnector(BufferCandidateSearchResult(
                ok=True,
                candidates=(
                    _candidate(task, post_id="ambiguous-1"),
                    _candidate(task, post_id="ambiguous-2"),
                ),
            )),
        )
        from apps.publishing.reconciliation import reconcile_unknown_buffer_publish_task

        reconcile_unknown_buffer_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_NOT_PUBLISHED,
            actor=publishing_context["actor"],
        )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    with pytest.raises(PublishingConflict):
        create_publish_task(
            content=publishing_context["content"],
            account=account,
            idempotency_key=f"blocked-{attention_kind}",
            actor=publishing_context["actor"],
        )


def test_strict_post_not_found_after_window_can_be_closed(
    publishing_context, monkeypatch,
):
    task, account = _post_not_found_attention(publishing_context, monkeypatch)

    resolved = resolve_publish_task(
        task,
        resolution=CONFIRM_NOT_PUBLISHED,
        actor=publishing_context["actor"],
    )

    resolved.refresh_from_db()
    assert resolved.status == PublishTask.Status.FAILED
    assert resolved.last_error["code"] == "MANUALLY_CLOSED_NO_POST"
    replacement = create_publish_task(
        content=publishing_context["content"],
        account=account,
        idempotency_key="after-strict-post-not-found",
        actor=publishing_context["actor"],
    )
    assert replacement.id != task.id


@pytest.mark.parametrize(
    "result",
    [
        BufferPostQueryResult(ok=False, error_code="BUFFER_POST_NOT_FOUND"),
        _sent_result(post_id="different-post"),
        _sent_result(channel_id="wrong-channel"),
        _sent_result(service="linkedin"),
        _sent_result(status="scheduled"),
    ],
    ids=["not-found", "different-id", "wrong-channel", "wrong-platform", "not-sent"],
)
def test_unverified_buffer_post_cannot_be_confirmed_published(
    publishing_context, monkeypatch, result,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    connector = ManualFetchConnector(result)
    _resolution_runtime(monkeypatch, connector)

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_PUBLISHED,
            provider_post_id="buffer-manual-post-1",
            actor=publishing_context["actor"],
        )

    task.refresh_from_db()
    publishing_context["content"].refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert publishing_context["content"].status == PlatformContent.Status.APPROVED
    assert not PublishedPost.objects.filter(task=task).exists()
    assert connector.publish_calls == 0


def test_buffer_unavailable_during_manual_confirmation_preserves_attention(
    publishing_context, monkeypatch,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)
    connector = ManualFetchConnector(
        BufferPostQueryResult(ok=False, error_code="BUFFER_PROVIDER_UNAVAILABLE")
    )
    _resolution_runtime(monkeypatch, connector)

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_PUBLISHED,
            provider_post_id="buffer-manual-post-1",
            actor=publishing_context["actor"],
        )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert not PublishedPost.objects.filter(task=task).exists()
    assert connector.publish_calls == 0


@pytest.mark.parametrize("changed_object", ["task", "connection"])
def test_snapshot_change_during_buffer_fetch_cannot_overwrite_attention(
    publishing_context, monkeypatch, changed_object,
):
    task, _account = _needs_attention(publishing_context, monkeypatch)

    def change_snapshot():
        if changed_object == "task":
            from apps.publishing.models import publishing_writes

            with publishing_writes():
                current = PublishTask.objects.get(pk=task.pk)
                current.next_reconcile_at = timezone.now() + timedelta(minutes=5)
                current.save(update_fields=["next_reconcile_at", "updated_at"])
        else:
            connection = task.social_account.provider_connection
            connection.display_name = "Rotated during manual fetch"
            connection.save(update_fields=["display_name", "updated_at"])

    connector = ManualFetchConnector(_sent_result(), on_fetch=change_snapshot)
    _resolution_runtime(monkeypatch, connector)

    with pytest.raises(PublishingConflict):
        resolve_publish_task(
            task,
            resolution=CONFIRM_PUBLISHED,
            provider_post_id="buffer-manual-post-1",
            actor=publishing_context["actor"],
        )

    task.refresh_from_db()
    assert task.status == PublishTask.Status.NEEDS_ATTENTION
    assert not PublishedPost.objects.filter(task=task).exists()
    assert connector.publish_calls == 0


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
