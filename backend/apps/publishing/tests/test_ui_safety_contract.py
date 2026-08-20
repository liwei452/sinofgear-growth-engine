import pytest

from apps.publishing.models import PublishedPost, PublishTask
from apps.publishing.serializers import PublishTaskSerializer
from apps.publishing.services import (
    create_publish_task,
    execute_publish_task,
    publish_task_consistency_queryset,
)
from integrations.platforms.base import PublishResult

from .test_async_publish_states import _patch_connector
from .test_buffer_manual_resolution import _needs_attention, _no_match_attention
from .test_buffer_reconciliation import _submitted, _unknown


def _serialized(context, task):
    loaded = publish_task_consistency_queryset(context["organization"]).get(pk=task.pk)
    return PublishTaskSerializer(loaded).data


def _failed(context, monkeypatch, *, code="PROVIDER_ERROR", retry_after=None, suffix="one"):
    _patch_connector(
        monkeypatch,
        PublishResult(
            succeeded=False,
            error_code=code,
            retry_after_seconds=retry_after,
        ),
    )
    task = create_publish_task(
        content=context["content"],
        account=context["account"],
        idempotency_key=f"ui-failed-{code}-{retry_after}-{suffix}",
        actor=context["actor"],
    )
    execute_publish_task(task.id)
    task.refresh_from_db()
    assert task.status == PublishTask.Status.FAILED
    return task


def test_failed_task_exposes_retry_without_mutating_or_dispatching(
    publishing_context, monkeypatch,
):
    task = _failed(publishing_context, monkeypatch)
    before = (task.updated_at, task.attempt_number)

    payload = _serialized(publishing_context, task)

    task.refresh_from_db()
    assert payload["allowed_actions"] == {
        "retry": {"allowed": True, "reason_code": None},
        "reconcile": {"allowed": False, "reason_code": "STATUS_NOT_RECONCILABLE"},
        "confirm_published": {"allowed": False, "reason_code": "STATUS_NOT_RESOLVABLE"},
        "confirm_not_published": {"allowed": False, "reason_code": "STRICT_NO_MATCH_REQUIRED"},
    }
    assert (task.updated_at, task.attempt_number) == before


def test_retry_is_blocked_for_rate_limit_auth_and_uncertain_states(
    publishing_context, monkeypatch,
):
    rate_limited = _failed(
        publishing_context, monkeypatch, code="RATE_LIMITED", retry_after=60,
    )
    assert _serialized(publishing_context, rate_limited)["allowed_actions"]["retry"] == {
        "allowed": False,
        "reason_code": "RETRY_DELAY_ACTIVE",
    }
    auth_failed = _failed(
        publishing_context, monkeypatch, code="TOKEN_EXPIRED", suffix="auth",
    )
    assert _serialized(publishing_context, auth_failed)["allowed_actions"]["retry"] == {
        "allowed": False,
        "reason_code": "REAUTHORIZATION_REQUIRED",
    }


@pytest.mark.parametrize("state", ["submitted", "unknown", "attention"])
def test_uncertain_or_attention_task_never_offers_retry(
    publishing_context, monkeypatch, state,
):
    if state == "submitted":
        task, _account, _connection = _submitted(publishing_context, monkeypatch)
    elif state == "unknown":
        task, _account, _connection = _unknown(publishing_context, monkeypatch)
    else:
        task, _account = _needs_attention(publishing_context, monkeypatch)

    retry = _serialized(publishing_context, task)["allowed_actions"]["retry"]
    assert retry == {"allowed": False, "reason_code": "STATUS_NOT_RETRYABLE"}


@pytest.mark.parametrize("state", ["submitted", "unknown"])
def test_only_valid_buffer_uncertain_tasks_offer_read_only_reconciliation(
    publishing_context, monkeypatch, state,
):
    factory = _submitted if state == "submitted" else _unknown
    task, _account, _connection = factory(publishing_context, monkeypatch)

    actions = _serialized(publishing_context, task)["allowed_actions"]

    assert actions["reconcile"] == {"allowed": True, "reason_code": None}
    assert actions["confirm_published"]["allowed"] is False
    assert not PublishedPost.objects.filter(task=task).exists()


def test_needs_attention_exposes_only_safe_manual_resolution_actions(
    publishing_context, monkeypatch,
):
    draft, _account = _needs_attention(publishing_context, monkeypatch)
    draft_payload = _serialized(publishing_context, draft)
    assert draft_payload["allowed_actions"]["confirm_published"] == {
        "allowed": True,
        "reason_code": None,
    }
    assert draft_payload["allowed_actions"]["confirm_not_published"] == {
        "allowed": False,
        "reason_code": "STRICT_NO_MATCH_REQUIRED",
    }


def test_strict_no_match_after_window_exposes_safe_evidence_and_close_action(
    publishing_context, monkeypatch,
):
    task, _account = _no_match_attention(publishing_context, monkeypatch)

    payload = _serialized(publishing_context, task)

    assert payload["allowed_actions"]["confirm_not_published"] == {
        "allowed": True,
        "reason_code": None,
    }
    assert payload["resolution_evidence"] == {
        "latest_outcome": "NEEDS_ATTENTION",
        "candidate_count": 0,
        "query_window_end": payload["resolution_evidence"]["query_window_end"],
        "query_window_ended": True,
        "ambiguous": False,
        "truncated": False,
        "snapshot_valid": True,
        "observed_at": payload["resolution_evidence"]["observed_at"],
    }
    serialized = str(payload)
    for secret in (
        task.request_fingerprint,
        task.provider_request_fingerprint,
        "credential_reference",
        "provider_metadata",
        "connector_metadata",
    ):
        assert secret not in serialized


def test_no_evidence_is_safe_and_does_not_offer_manual_close(
    publishing_context, monkeypatch,
):
    task, _account, _connection = _unknown(publishing_context, monkeypatch)

    payload = _serialized(publishing_context, task)

    assert payload["resolution_evidence"] == {
        "latest_outcome": None,
        "candidate_count": None,
        "query_window_end": None,
        "query_window_ended": False,
        "ambiguous": False,
        "truncated": False,
        "snapshot_valid": False,
        "observed_at": None,
    }
    assert payload["allowed_actions"]["confirm_not_published"]["allowed"] is False


def test_publish_task_list_contract_query_count_is_constant(
    publishing_context, monkeypatch, django_assert_num_queries,
):
    tasks_created = [
        _failed(publishing_context, monkeypatch, suffix=str(index))
        for index in range(4)
    ]
    # Reading the canonical list remains fixed-query and eligibility performs no I/O.
    with django_assert_num_queries(4):
        tasks = list(publish_task_consistency_queryset(publishing_context["organization"]))
        payload = PublishTaskSerializer(tasks, many=True).data
    assert {item["id"] for item in payload} == {str(task.id) for task in tasks_created}
