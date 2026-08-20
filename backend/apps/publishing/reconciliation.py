from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.content.services import transition_content
from apps.platforms.models import ProviderConnection, SocialAccount
from integrations.platforms.buffer_types import (
    BufferPostObservation,
    BufferPostQueryRequest,
    BufferPostQueryResult,
)
from integrations.platforms.runtime import get_social_provider_runtime

from .models import (
    PublishAttempt,
    PublishedPost,
    PublishReconciliationAttempt,
    PublishTask,
    publishing_writes,
)
from .services import PublishingConflict


BUFFER_RECONCILIATION_BATCH_SIZE = 50
BUFFER_RECONCILIATION_MAX_AGE = timedelta(days=7)
BUFFER_RECONCILIATION_MAX_DELAY = timedelta(hours=6)
BUFFER_RECONCILIATION_DISPATCH_LEASE = timedelta(minutes=5)

SAFE_RECONCILIATION_ERRORS = {
    "BUFFER_PUBLISH_FAILED": "Buffer confirmed that publishing failed.",
    "BUFFER_POST_NOT_FOUND": "The submitted Buffer post could not be found.",
    "BUFFER_POST_MISMATCH": "The Buffer post did not match the submitted task.",
    "BUFFER_CONTRACT_ERROR": "Buffer returned an invalid post status response.",
    "BUFFER_AUTHENTICATION_REQUIRED": "Buffer authorization must be renewed.",
    "BUFFER_RATE_LIMITED": "Buffer reconciliation was rate limited.",
    "BUFFER_PROVIDER_UNAVAILABLE": "Buffer reconciliation is temporarily unavailable.",
    "BUFFER_RECONCILIATION_STALE": "The task changed while Buffer was being queried.",
    "BUFFER_RECONCILIATION_EXPIRED": "The Buffer post remained non-final for too long.",
}


@dataclass(frozen=True, repr=False)
class ReconciliationSnapshot:
    task_id: object
    organization_id: object
    task_updated_at: object
    provider_submission_id: str
    account_id: object
    account_updated_at: object
    provider_account_id: str
    platform_code: str
    connection_id: object
    connection_updated_at: object
    credential_reference: str
    started_at: object


def _valid_identifier(value) -> bool:
    return type(value) is str and bool(value.strip()) and len(value.strip()) <= 255


def load_reconciliation_snapshot(task_id, *, organization=None) -> ReconciliationSnapshot:
    queryset = PublishTask.objects.select_related(
        "social_account__platform", "social_account__provider_connection"
    )
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    try:
        task = queryset.get(pk=task_id)
    except (PublishTask.DoesNotExist, ValueError) as exc:
        raise PublishingConflict("Publish task is not available for reconciliation.") from exc
    account = task.social_account
    connection = account.provider_connection
    if (
        task.status != PublishTask.Status.SUBMITTED
        or account.provider != SocialAccount.Provider.BUFFER
        or connection is None
        or connection.provider != ProviderConnection.Provider.BUFFER
        or not _valid_identifier(task.provider_submission_id)
        or not _valid_identifier(account.provider_account_id)
    ):
        raise PublishingConflict("Only submitted Buffer tasks can be reconciled.")
    return ReconciliationSnapshot(
        task_id=task.id,
        organization_id=task.organization_id,
        task_updated_at=task.updated_at,
        provider_submission_id=task.provider_submission_id.strip(),
        account_id=account.id,
        account_updated_at=account.updated_at,
        provider_account_id=account.provider_account_id.strip(),
        platform_code=account.platform.code,
        connection_id=connection.id,
        connection_updated_at=connection.updated_at,
        credential_reference=connection.credential_reference,
        started_at=timezone.now(),
    )


def reconcile_buffer_publish_task(task_id, *, organization=None, actor=None):
    snapshot = load_reconciliation_snapshot(task_id, organization=organization)
    account = SocialAccount.objects.select_related("platform", "provider_connection").get(
        pk=snapshot.account_id
    )
    try:
        connector = get_social_provider_runtime().connector_registry.resolve(account)
    except Exception:
        result = BufferPostQueryResult(
            ok=False, error_code="BUFFER_CONFIGURATION_REQUIRED"
        )
    else:
        try:
            result = connector.fetch_post(
                BufferPostQueryRequest(
                    credential_reference=snapshot.credential_reference,
                    provider_submission_id=snapshot.provider_submission_id,
                )
            )
        except Exception:
            result = BufferPostQueryResult(
                ok=False, error_code="BUFFER_PROVIDER_UNAVAILABLE"
            )
    return finalize_buffer_reconciliation(snapshot, result, actor=actor)


def _delay_for(number: int) -> timedelta:
    seconds = min(60 * (2 ** min(max(number - 1, 0), 8)), int(BUFFER_RECONCILIATION_MAX_DELAY.total_seconds()))
    return timedelta(seconds=seconds)


def _latest_attempt(task):
    attempt = PublishAttempt.objects.select_for_update().filter(task=task).order_by("-number").first()
    if attempt is None or attempt.status != PublishAttempt.Status.SUBMITTED:
        raise PublishingConflict("Submitted publish attempt is inconsistent.")
    return attempt


def _record(task, *, result, started_at, finished_at, observed="", error_code="", observation=None):
    task.reconciliation_attempt_number += 1
    with publishing_writes():
        PublishReconciliationAttempt.objects.create(
            organization_id=task.organization_id,
            publish_task=task,
            sequence_number=task.reconciliation_attempt_number,
            result=result,
            provider_submission_id=task.provider_submission_id,
            observed_provider_status=observed,
            safe_error_code=error_code,
            provider_post_id=observation.post_id if observation else "",
            provider_channel_id=observation.channel_id if observation else "",
            provider_sent_at=observation.sent_at if observation else None,
            started_at=started_at,
            finished_at=finished_at,
        )


def _snapshot_matches(snapshot, task, account, connection) -> bool:
    return (
        task.status == PublishTask.Status.SUBMITTED
        and task.updated_at == snapshot.task_updated_at
        and task.provider_submission_id == snapshot.provider_submission_id
        and account.updated_at == snapshot.account_updated_at
        and account.provider_account_id == snapshot.provider_account_id
        and connection.updated_at == snapshot.connection_updated_at
        and connection.credential_reference == snapshot.credential_reference
    )


@transaction.atomic
def finalize_buffer_reconciliation(snapshot, result: BufferPostQueryResult, *, actor=None):
    finished_at = timezone.now()
    task = PublishTask.objects.select_for_update().select_related("platform_content").get(
        pk=snapshot.task_id, organization_id=snapshot.organization_id
    )
    account = SocialAccount.objects.select_for_update().select_related("platform").get(
        pk=snapshot.account_id, organization_id=snapshot.organization_id
    )
    connection = ProviderConnection.objects.select_for_update().get(
        pk=snapshot.connection_id, organization_id=snapshot.organization_id
    )
    started_at = snapshot.started_at
    if not _snapshot_matches(snapshot, task, account, connection):
        if task.status == PublishTask.Status.SUBMITTED:
            _record(
                task, result=PublishReconciliationAttempt.Result.STALE,
                started_at=started_at, finished_at=finished_at,
                error_code="BUFFER_RECONCILIATION_STALE",
            )
            task.last_reconciled_at = finished_at
            task.reconciliation_error_code = "BUFFER_RECONCILIATION_STALE"
            with publishing_writes():
                task.save(update_fields=[
                    "reconciliation_attempt_number", "last_reconciled_at",
                    "reconciliation_error_code", "updated_at",
                ])
        return task

    attempt = _latest_attempt(task)
    if type(result) is not BufferPostQueryResult:
        result = BufferPostQueryResult(ok=False, error_code="BUFFER_CONTRACT_ERROR")
    if not result.ok:
        return _finalize_query_error(task, attempt, account, connection, result, started_at, finished_at)
    observation = result.observation
    if type(observation) is not BufferPostObservation:
        return _needs_attention(task, attempt, started_at, finished_at, "BUFFER_CONTRACT_ERROR")
    mismatch = (
        observation.post_id != snapshot.provider_submission_id
        or observation.channel_id != snapshot.provider_account_id
        or observation.channel_service.upper() != snapshot.platform_code.upper()
    )
    if mismatch:
        return _needs_attention(
            task, attempt, started_at, finished_at, "BUFFER_POST_MISMATCH", observation
        )
    if observation.status == "sent":
        if observation.sent_at is None or observation.sent_at > finished_at:
            return _needs_attention(
                task, attempt, started_at, finished_at, "BUFFER_CONTRACT_ERROR", observation
            )
        return _succeed(task, attempt, started_at, finished_at, observation, actor)
    if observation.status in {"scheduled", "sending"}:
        if task.provider_call_started_at and finished_at - task.provider_call_started_at > BUFFER_RECONCILIATION_MAX_AGE:
            return _needs_attention(
                task, attempt, started_at, finished_at, "BUFFER_RECONCILIATION_EXPIRED", observation
            )
        return _defer(task, started_at, finished_at, observation=observation)
    if observation.status == "error":
        return _fail(task, attempt, started_at, finished_at, observation)
    return _needs_attention(task, attempt, started_at, finished_at, "BUFFER_CONTRACT_ERROR", observation)


def _save_task_reconciliation(task, finished_at, *, error_code="", next_at=None):
    task.last_reconciled_at = finished_at
    task.next_reconcile_at = next_at
    task.reconciliation_error_code = error_code
    with publishing_writes():
        task.save(update_fields=[
            "status", "last_error", "finished_at", "reconciliation_attempt_number",
            "last_reconciled_at", "next_reconcile_at", "reconciliation_error_code", "updated_at",
        ])


def _defer(task, started_at, finished_at, *, error_code="", retry_after=None, observation=None):
    delay = timedelta(seconds=min(max(retry_after or 0, 1), 21600)) if retry_after else _delay_for(task.reconciliation_attempt_number + 1)
    _record(
        task, result=PublishReconciliationAttempt.Result.DEFERRED,
        started_at=started_at, finished_at=finished_at,
        observed=observation.status if observation else "", error_code=error_code,
        observation=observation,
    )
    _save_task_reconciliation(task, finished_at, error_code=error_code, next_at=finished_at + delay)
    return task


def _needs_attention(task, attempt, started_at, finished_at, error_code, observation=None):
    error = {"code": error_code, "message": SAFE_RECONCILIATION_ERRORS[error_code]}
    task.status = PublishTask.Status.NEEDS_ATTENTION
    task.last_error = error
    task.finished_at = finished_at
    attempt.status = PublishAttempt.Status.NEEDS_ATTENTION
    attempt.outcome = "NEEDS_ATTENTION"
    attempt.error = error
    attempt.finished_at = finished_at
    _record(
        task, result=PublishReconciliationAttempt.Result.NEEDS_ATTENTION,
        started_at=started_at, finished_at=finished_at,
        observed=observation.status if observation else "", error_code=error_code,
        observation=observation,
    )
    with publishing_writes():
        attempt.save(update_fields=["status", "outcome", "error", "finished_at", "updated_at"])
    _save_task_reconciliation(task, finished_at, error_code=error_code)
    return task


def _fail(task, attempt, started_at, finished_at, observation):
    code = "BUFFER_PUBLISH_FAILED"
    error = {"code": code, "message": SAFE_RECONCILIATION_ERRORS[code]}
    task.status = PublishTask.Status.FAILED
    task.last_error = error
    task.finished_at = finished_at
    attempt.status = PublishAttempt.Status.FAILED
    attempt.outcome = code
    attempt.error = error
    attempt.finished_at = finished_at
    _record(
        task, result=PublishReconciliationAttempt.Result.FAILED,
        started_at=started_at, finished_at=finished_at,
        observed=observation.status, error_code=code, observation=observation,
    )
    with publishing_writes():
        attempt.save(update_fields=["status", "outcome", "error", "finished_at", "updated_at"])
    _save_task_reconciliation(task, finished_at, error_code=code)
    return task


def _succeed(task, attempt, started_at, finished_at, observation, actor):
    post = PublishedPost.objects.filter(task=task).first()
    if post is None:
        with publishing_writes():
            PublishedPost.objects.create(
                organization_id=task.organization_id,
                task=task,
                attempt=attempt,
                platform_content=task.platform_content,
                social_account_id=task.social_account_id,
                external_id=observation.post_id,
                published_at=observation.sent_at,
            )
    if task.platform_content.status == PlatformContent.Status.APPROVED:
        transition_content(
            task.platform_content, action="PUBLISH", actor=actor or task.created_by,
            comment="Buffer exact-id reconciliation confirmed publication.",
        )
    elif task.platform_content.status != PlatformContent.Status.PUBLISHED:
        return _needs_attention(
            task, attempt, started_at, finished_at, "BUFFER_CONTRACT_ERROR", observation
        )
    task.status = PublishTask.Status.SUCCEEDED
    task.last_error = None
    task.finished_at = finished_at
    attempt.status = PublishAttempt.Status.SUCCEEDED
    attempt.outcome = "SUCCEEDED"
    attempt.error = None
    attempt.external_id = observation.post_id
    attempt.finished_at = finished_at
    _record(
        task, result=PublishReconciliationAttempt.Result.SUCCEEDED,
        started_at=started_at, finished_at=finished_at,
        observed="sent", observation=observation,
    )
    with publishing_writes():
        attempt.save(update_fields=["status", "outcome", "error", "external_id", "finished_at", "updated_at"])
    _save_task_reconciliation(task, finished_at)
    return task


def _finalize_query_error(task, attempt, account, connection, result, started_at, finished_at):
    code = result.error_code if type(result.error_code) is str else "BUFFER_CONTRACT_ERROR"
    if code == "BUFFER_POST_NOT_FOUND":
        return _needs_attention(task, attempt, started_at, finished_at, code)
    if code in {"BUFFER_AUTHENTICATION_REQUIRED", "BUFFER_CONFIGURATION_REQUIRED"}:
        connection.connection_state = ProviderConnection.ConnectionState.REAUTHORIZATION_REQUIRED
        connection.reauthorization_required_at = finished_at
        connection.lifecycle_error_code = "BUFFER_AUTHENTICATION_REQUIRED"
        account.connection_state = SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
        account.reauthorization_required_at = finished_at
        account.lifecycle_error_code = "BUFFER_AUTHENTICATION_REQUIRED"
        connection.save(update_fields=[
            "connection_state", "reauthorization_required_at", "lifecycle_error_code", "updated_at"
        ])
        account.save(update_fields=[
            "connection_state", "reauthorization_required_at", "lifecycle_error_code", "updated_at"
        ])
        return _defer(task, started_at, finished_at, error_code="BUFFER_AUTHENTICATION_REQUIRED")
    if code == "BUFFER_RATE_LIMITED":
        return _defer(
            task, started_at, finished_at, error_code=code,
            retry_after=result.retry_after_seconds,
        )
    if code not in {"BUFFER_PROVIDER_UNAVAILABLE"}:
        code = "BUFFER_CONTRACT_ERROR"
        return _needs_attention(task, attempt, started_at, finished_at, code)
    return _defer(task, started_at, finished_at, error_code=code)


def select_due_buffer_reconciliation_ids(*, limit=BUFFER_RECONCILIATION_BATCH_SIZE, now=None):
    now = now or timezone.now()
    limit = min(max(int(limit), 1), BUFFER_RECONCILIATION_BATCH_SIZE)
    with transaction.atomic():
        tasks = list(
            PublishTask.objects.select_for_update(skip_locked=True)
            .filter(
                status=PublishTask.Status.SUBMITTED,
                social_account__provider=SocialAccount.Provider.BUFFER,
            )
            .exclude(provider_submission_id="")
            .filter(next_reconcile_at__isnull=True)
            .order_by("created_at", "id")[:limit]
        )
        if len(tasks) < limit:
            tasks += list(
                PublishTask.objects.select_for_update(skip_locked=True)
                .filter(
                    status=PublishTask.Status.SUBMITTED,
                    social_account__provider=SocialAccount.Provider.BUFFER,
                    next_reconcile_at__lte=now,
                )
                .exclude(provider_submission_id="")
                .exclude(pk__in=[task.pk for task in tasks])
                .order_by("next_reconcile_at", "id")[: limit - len(tasks)]
            )
        with publishing_writes():
            for task in tasks:
                task.next_reconcile_at = now + BUFFER_RECONCILIATION_DISPATCH_LEASE
                task.save(update_fields=["next_reconcile_at", "updated_at"])
        return [task.id for task in tasks]
