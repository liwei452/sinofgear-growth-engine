from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.content.services import transition_content
from apps.platforms.models import SocialAccount

from .models import (
    PublishAttempt,
    PublishedPost,
    PublishReconciliationAttempt,
    PublishTask,
    publishing_writes,
)
from .services import PublishingConflict, SAFE_PUBLISH_ERRORS


CONFIRM_PUBLISHED = "CONFIRM_PUBLISHED"
CONFIRM_NOT_PUBLISHED = "CONFIRM_NOT_PUBLISHED"
MANUAL_RESOLUTIONS = {CONFIRM_PUBLISHED, CONFIRM_NOT_PUBLISHED}


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


@transaction.atomic
def resolve_publish_task(
    task, *, resolution, provider_post_id="", actor=None, organization=None,
):
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
    try:
        task = (
            PublishTask.objects.select_for_update()
            .select_related("platform_content", "social_account")
            .get(pk=task.pk, organization_id=organization_id)
        )
    except PublishTask.DoesNotExist as exc:
        raise PublishingConflict("Publish task is not available for manual resolution.") from exc
    content = PlatformContent.objects.select_for_update().get(
        pk=task.platform_content_id,
        organization_id=task.organization_id,
    )
    account = SocialAccount.objects.select_for_update().get(
        pk=task.social_account_id,
        organization_id=task.organization_id,
    )
    if account.provider != SocialAccount.Provider.BUFFER:
        raise PublishingConflict("Only Buffer tasks support this manual resolution.")

    replay = _idempotent_result(task, resolution, provider_post_id)
    if replay is not None:
        return replay
    if task.status != PublishTask.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Only tasks needing attention can be manually resolved.")
    attempt = _latest_attempt(task)
    if attempt.status != PublishAttempt.Status.NEEDS_ATTENTION:
        raise PublishingConflict("Publish task attempt history is inconsistent.")

    finished_at = timezone.now()
    if resolution == CONFIRM_PUBLISHED:
        duplicate = PublishedPost.objects.filter(
            social_account=account,
            external_id=provider_post_id,
        ).exclude(task=task).exists()
        if duplicate:
            raise PublishingConflict("This Buffer post ID is already assigned to another task.")
        post = PublishedPost.objects.filter(task=task).first()
        if post is not None and post.external_id != provider_post_id:
            raise PublishingConflict("This task already references a different published post.")
        if post is None:
            with publishing_writes():
                PublishedPost.objects.create(
                    organization_id=task.organization_id,
                    task=task,
                    attempt=attempt,
                    platform_content=content,
                    social_account=account,
                    external_id=provider_post_id,
                    published_at=finished_at,
                )
        if content.status == PlatformContent.Status.APPROVED:
            transition_content(
                content,
                action="PUBLISH",
                actor=actor,
                comment="Authorized operator confirmed the Buffer post ID.",
            )
        elif content.status != PlatformContent.Status.PUBLISHED:
            raise PublishingConflict("Content is not eligible for published confirmation.")
        task.status = PublishTask.Status.SUCCEEDED
        task.provider_submission_id = provider_post_id
        task.last_error = None
        attempt.status = PublishAttempt.Status.SUCCEEDED
        attempt.provider_submission_id = provider_post_id
        attempt.external_id = provider_post_id
        attempt.outcome = "SUCCEEDED"
        attempt.error = None
        audit_result = PublishReconciliationAttempt.Result.SUCCEEDED
        error_code = ""
    else:
        error_code = "MANUALLY_CLOSED_NO_POST"
        error = SAFE_PUBLISH_ERRORS[error_code]
        task.status = PublishTask.Status.FAILED
        task.last_error = error
        attempt.status = PublishAttempt.Status.FAILED
        attempt.outcome = error_code
        attempt.error = error
        audit_result = PublishReconciliationAttempt.Result.FAILED

    task.claim_token = None
    task.retry_not_before = None
    task.finished_at = finished_at
    task.next_reconcile_at = None
    task.last_reconciled_at = finished_at
    task.reconciliation_error_code = error_code
    attempt.finished_at = finished_at
    _record_manual_resolution(
        task,
        actor=actor,
        result=audit_result,
        finished_at=finished_at,
        provider_post_id=(provider_post_id if resolution == CONFIRM_PUBLISHED else ""),
        error_code=error_code,
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
