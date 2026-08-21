from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.content.models import PlatformContent
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
from .eligibility import strict_no_post_evidence
from .reconciliation import apply_confirmed_publish_success
from .services import PublishingConflict, SAFE_PUBLISH_ERRORS


CONFIRM_PUBLISHED = "CONFIRM_PUBLISHED"
CONFIRM_NOT_PUBLISHED = "CONFIRM_NOT_PUBLISHED"
MANUAL_RESOLUTIONS = {CONFIRM_PUBLISHED, CONFIRM_NOT_PUBLISHED}


@dataclass(frozen=True, repr=False)
class ManualPublishSnapshot:
    task_id: object
    organization_id: object
    task_updated_at: object
    attempt_id: object
    attempt_updated_at: object
    account_id: object
    account_updated_at: object
    provider_account_id: str
    platform_code: str
    connection_id: object
    connection_updated_at: object
    credential_reference: str


def _valid_provider_post_id(value) -> bool:
    return type(value) is str and bool(value.strip()) and len(value.strip()) <= 255


def _latest_attempt(task):
    attempt = (
        PublishAttempt.objects.select_for_update()
        .filter(task=task, organization_id=task.organization_id)
        .order_by("-number")
        .first()
    )
    if attempt is None:
        raise PublishingConflict("Publish task attempt history is unavailable.")
    return attempt


def _manual_audit(task):
    return (
        PublishReconciliationAttempt.objects.filter(
            publish_task=task,
            organization_id=task.organization_id,
            mode=PublishReconciliationAttempt.Mode.MANUAL,
        )
        .order_by("sequence_number")
        .first()
    )


def _idempotent_result(task, resolution, provider_post_id):
    audit = _manual_audit(task)
    if audit is None:
        return None
    if (
        resolution == CONFIRM_PUBLISHED
        and task.status == PublishTask.Status.SUCCEEDED
        and audit.result == PublishReconciliationAttempt.Result.SUCCEEDED
        and audit.matched_provider_post_id == provider_post_id
    ):
        return task
    if (
        resolution == CONFIRM_NOT_PUBLISHED
        and task.status == PublishTask.Status.FAILED
        and audit.result == PublishReconciliationAttempt.Result.FAILED
        and audit.safe_error_code == "MANUALLY_CLOSED_NO_POST"
    ):
        return task
    raise PublishingConflict("This publish task already has a different manual resolution.")


def _record_manual_resolution(
    task, *, actor, result, finished_at, provider_post_id="", error_code="",
):
    task.reconciliation_attempt_number += 1
    with publishing_writes():
        PublishReconciliationAttempt.objects.create(
            organization_id=task.organization_id,
            publish_task=task,
            sequence_number=task.reconciliation_attempt_number,
            mode=PublishReconciliationAttempt.Mode.MANUAL,
            result=result,
            provider_submission_id=provider_post_id or task.provider_submission_id,
            observed_provider_status="MANUALLY_CONFIRMED",
            safe_error_code=error_code,
            provider_post_id=provider_post_id,
            matched_provider_post_id=provider_post_id,
            resolved_by=actor,
            started_at=finished_at,
            finished_at=finished_at,
        )


def _validate_common_inputs(task, resolution, provider_post_id, actor, organization):
    if type(resolution) is not str or resolution not in MANUAL_RESOLUTIONS:
        raise PublishingConflict("Provide a supported manual resolution.")
    if actor is None:
        raise PublishingConflict("Manual resolution requires an auditable actor.")
    if resolution == CONFIRM_PUBLISHED:
        if not _valid_provider_post_id(provider_post_id):
            raise PublishingConflict("Provide a valid Buffer post ID.")
        provider_post_id = provider_post_id.strip()
    elif not (
        provider_post_id is None
        or (type(provider_post_id) is str and provider_post_id == "")
    ):
        raise PublishingConflict("A post ID is not allowed when confirming no post.")
    organization_id = organization.pk if organization is not None else task.organization_id
    return organization_id, provider_post_id


def _locked_task(task_id, organization_id):
    try:
        return (
            PublishTask.objects.select_for_update()
            .select_related("platform_content", "social_account")
            .get(pk=task_id, organization_id=organization_id)
        )
    except PublishTask.DoesNotExist as exc:
        raise PublishingConflict("Publish task is not available for manual resolution.") from exc


def _lock_buffer_dependencies(task):
    content = PlatformContent.objects.select_for_update().get(
        pk=task.platform_content_id, organization_id=task.organization_id
    )
    account = SocialAccount.objects.select_for_update().select_related("platform").get(
        pk=task.social_account_id, organization_id=task.organization_id
    )
    if account.provider != SocialAccount.Provider.BUFFER or account.provider_connection_id is None:
        raise PublishingConflict("Only Buffer tasks support this manual resolution.")
    connection = ProviderConnection.objects.select_for_update().get(
        pk=account.provider_connection_id, organization_id=task.organization_id
    )
    return content, account, connection


@transaction.atomic
def _load_publish_snapshot(task_id, organization_id, provider_post_id):
    task = _locked_task(task_id, organization_id)
    replay = _idempotent_result(task, CONFIRM_PUBLISHED, provider_post_id)
    if replay is not None:
        return replay
    if task.status != PublishTask.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Only tasks needing attention can be manually resolved.")
    attempt = _latest_attempt(task)
    if attempt.status != PublishAttempt.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Publish task attempt history is inconsistent.")
    _content, account, connection = _lock_buffer_dependencies(task)
    return ManualPublishSnapshot(
        task_id=task.id,
        organization_id=task.organization_id,
        task_updated_at=task.updated_at,
        attempt_id=attempt.id,
        attempt_updated_at=attempt.updated_at,
        account_id=account.id,
        account_updated_at=account.updated_at,
        provider_account_id=account.provider_account_id,
        platform_code=account.platform.code,
        connection_id=connection.id,
        connection_updated_at=connection.updated_at,
        credential_reference=connection.credential_reference,
    )


def _fetch_verified_post(snapshot, provider_post_id):
    try:
        account = SocialAccount.objects.select_related("platform", "provider_connection").get(
            pk=snapshot.account_id, organization_id=snapshot.organization_id
        )
        connector = get_social_provider_runtime().connector_registry.resolve(account)
        result = connector.fetch_post(BufferPostQueryRequest(
            credential_reference=snapshot.credential_reference,
            provider_submission_id=provider_post_id,
        ))
    except Exception:
        raise PublishingConflict("Buffer could not verify this post. Try again later.") from None
    if type(result) is not BufferPostQueryResult or not result.ok:
        raise PublishingConflict("Buffer could not verify this post. Try again later.")
    observation = result.observation
    if type(observation) is not BufferPostObservation:
        raise PublishingConflict("Buffer did not return a valid sent post.")
    try:
        matches = (
            observation.post_id == provider_post_id
            and observation.channel_id == snapshot.provider_account_id
            and type(observation.channel_service) is str
            and observation.channel_service.upper() == snapshot.platform_code.upper()
            and observation.status == "sent"
            and observation.sent_at is not None
            and timezone.is_aware(observation.sent_at)
            and observation.sent_at <= timezone.now()
        )
    except Exception:
        matches = False
    if not matches:
        raise PublishingConflict("The Buffer post does not match this account or is not sent.")
    return observation


def _snapshot_still_matches(snapshot, task, attempt, account, connection):
    return (
        task.status == PublishTask.Status.NEEDS_ATTENTION
        and attempt.status == PublishAttempt.Status.NEEDS_ATTENTION
        and task.updated_at == snapshot.task_updated_at
        and attempt.id == snapshot.attempt_id
        and attempt.updated_at == snapshot.attempt_updated_at
        and account.id == snapshot.account_id
        and account.updated_at == snapshot.account_updated_at
        and account.provider_account_id == snapshot.provider_account_id
        and account.platform.code == snapshot.platform_code
        and connection.id == snapshot.connection_id
        and connection.updated_at == snapshot.connection_updated_at
        and connection.credential_reference == snapshot.credential_reference
    )


@transaction.atomic
def _finalize_confirm_published(snapshot, observation, *, actor):
    task = _locked_task(snapshot.task_id, snapshot.organization_id)
    replay = _idempotent_result(task, CONFIRM_PUBLISHED, observation.post_id)
    if replay is not None:
        return replay
    attempt = _latest_attempt(task)
    _content, account, connection = _lock_buffer_dependencies(task)
    if not _snapshot_still_matches(snapshot, task, attempt, account, connection):
        raise PublishingConflict("The publish task changed while Buffer was being checked.")
    duplicate = PublishedPost.objects.filter(
        social_account=account, external_id=observation.post_id
    ).exclude(task=task).exists()
    if duplicate:
        raise PublishingConflict("This Buffer post ID is already assigned to another task.")
    finished_at = timezone.now()
    apply_confirmed_publish_success(
        task, attempt, observation, actor=actor, finished_at=finished_at
    )
    task.last_reconciled_at = finished_at
    _record_manual_resolution(
        task,
        actor=actor,
        result=PublishReconciliationAttempt.Result.SUCCEEDED,
        finished_at=finished_at,
        provider_post_id=observation.post_id,
    )
    with publishing_writes():
        attempt.save(update_fields=[
            "status", "provider_submission_id", "external_id", "outcome", "error",
            "finished_at", "updated_at",
        ])
        task.save(update_fields=[
            "status", "provider_submission_id", "last_error", "claim_token",
            "retry_not_before", "finished_at", "next_reconcile_at",
            "last_reconciled_at", "reconciliation_error_code",
            "reconciliation_attempt_number", "updated_at",
        ])
    return task


def _latest_reconciliation(task):
    return (
        PublishReconciliationAttempt.objects.select_for_update()
        .filter(publish_task=task, organization_id=task.organization_id)
        .order_by("-sequence_number")
        .first()
    )


@transaction.atomic
def _confirm_not_published(task_id, organization_id, *, actor):
    task = _locked_task(task_id, organization_id)
    replay = _idempotent_result(task, CONFIRM_NOT_PUBLISHED, "")
    if replay is not None:
        return replay
    if task.status != PublishTask.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Only tasks needing attention can be manually resolved.")
    attempt = _latest_attempt(task)
    if attempt.status != PublishAttempt.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Publish task attempt history is inconsistent.")
    _content, account, connection = _lock_buffer_dependencies(task)
    finished_at = timezone.now()
    audit = _latest_reconciliation(task)
    if not strict_no_post_evidence(task, audit, account, connection, finished_at):
        raise PublishingConflict("Buffer has not provided strict evidence that no post exists.")
    error_code = "MANUALLY_CLOSED_NO_POST"
    error = SAFE_PUBLISH_ERRORS[error_code]
    task.status = PublishTask.Status.FAILED
    task.last_error = error
    task.claim_token = None
    task.retry_not_before = None
    task.finished_at = finished_at
    task.next_reconcile_at = None
    task.last_reconciled_at = finished_at
    task.reconciliation_error_code = error_code
    attempt.status = PublishAttempt.Status.FAILED
    attempt.outcome = error_code
    attempt.error = error
    attempt.finished_at = finished_at
    _record_manual_resolution(
        task,
        actor=actor,
        result=PublishReconciliationAttempt.Result.FAILED,
        finished_at=finished_at,
        error_code=error_code,
    )
    with publishing_writes():
        attempt.save(update_fields=["status", "outcome", "error", "finished_at", "updated_at"])
        task.save(update_fields=[
            "status", "last_error", "claim_token", "retry_not_before", "finished_at",
            "next_reconcile_at", "last_reconciled_at", "reconciliation_error_code",
            "reconciliation_attempt_number", "updated_at",
        ])
    return task


def resolve_publish_task(
    task, *, resolution, provider_post_id="", actor=None, organization=None,
):
    organization_id, provider_post_id = _validate_common_inputs(
        task, resolution, provider_post_id, actor, organization
    )
    if resolution == CONFIRM_NOT_PUBLISHED:
        return _confirm_not_published(task.pk, organization_id, actor=actor)
    snapshot = _load_publish_snapshot(task.pk, organization_id, provider_post_id)
    if isinstance(snapshot, PublishTask):
        return snapshot
    observation = _fetch_verified_post(snapshot, provider_post_id)
    return _finalize_confirm_published(snapshot, observation, actor=actor)
