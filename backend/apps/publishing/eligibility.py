from __future__ import annotations

from django.utils import timezone

from apps.content.models import PlatformContent
from apps.platforms.capabilities import resolve_loaded_account_capabilities
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ProviderConnection, SocialAccount

from .models import PublishAttempt, PublishedPost, PublishReconciliationAttempt, PublishTask


AUTH_ERROR_CODES = {"TOKEN_EXPIRED", "REAUTHORIZATION_REQUIRED"}
SAFE_EVIDENCE_RESULTS = set(PublishReconciliationAttempt.Result.values)
SAFE_EVIDENCE_CODES = {
    "BUFFER_POST_NOT_FOUND",
    "BUFFER_POST_MISMATCH",
    "BUFFER_RECONCILIATION_AMBIGUOUS",
    "BUFFER_RECONCILIATION_EVIDENCE_MISSING",
    "BUFFER_RECONCILIATION_EXPIRED",
    "BUFFER_RECONCILIATION_NO_MATCH",
    "BUFFER_PROVIDER_UNAVAILABLE",
    "BUFFER_RATE_LIMITED",
    "BUFFER_AUTHENTICATION_REQUIRED",
}


def _action(allowed: bool, reason_code: str | None = None) -> dict:
    return {"allowed": allowed, "reason_code": None if allowed else reason_code}


def _latest_attempt(task):
    attempts = getattr(task, "_safe_attempts", ())
    return max(attempts, key=lambda item: item.number, default=None)


def _latest_audit(task):
    audits = [
        audit for audit in getattr(task, "_safe_reconciliation_attempts", ())
        if audit.organization_id == task.organization_id
    ]
    return max(audits, key=lambda item: (item.sequence_number, item.id), default=None)


def _buffer_dependencies(task):
    account = task.social_account
    connection = account.provider_connection
    valid = (
        account.organization_id == task.organization_id
        and account.provider == SocialAccount.Provider.BUFFER
        and connection is not None
        and connection.organization_id == task.organization_id
        and connection.provider == ProviderConnection.Provider.BUFFER
    )
    return account, connection, valid


def strict_no_post_evidence(
    task, audit, account, connection, now, *, published_post_exists=None,
):
    """Shared, side-effect-free predicate; mutation callers may request its DB check."""
    if audit is None or audit.result != PublishReconciliationAttempt.Result.NEEDS_ATTENTION:
        return False
    if audit.candidate_count != 0 or audit.query_window_end is None or audit.query_window_end > now:
        return False
    if task.last_reconciled_at != audit.finished_at or task.reconciliation_error_code != audit.safe_error_code:
        return False
    if account.updated_at > audit.finished_at or connection.updated_at > audit.finished_at:
        return False
    if published_post_exists is None:
        published_post_exists = PublishedPost.objects.filter(task=task).exists()
    if published_post_exists or audit.observed_provider_status:
        return False
    if audit.safe_error_code == "BUFFER_RECONCILIATION_NO_MATCH":
        return (
            audit.mode == PublishReconciliationAttempt.Mode.UNKNOWN_MATCH
            and not task.provider_submission_id
            and not audit.provider_submission_id
        )
    if audit.safe_error_code == "BUFFER_POST_NOT_FOUND":
        return (
            audit.mode == PublishReconciliationAttempt.Mode.EXACT_ID
            and bool(task.provider_submission_id)
            and audit.provider_submission_id == task.provider_submission_id
        )
    return False


def _retry_action(task, now):
    if task.status != PublishTask.Status.FAILED:
        return _action(False, "STATUS_NOT_RETRYABLE")
    code = task.last_error.get("code") if type(task.last_error) is dict else ""
    if code == "MANUALLY_CLOSED_NO_POST":
        return _action(False, "CREATE_NEW_TASK_REQUIRED")
    if task.attempt_number >= 10:
        return _action(False, "ATTEMPT_LIMIT_REACHED")
    if code in AUTH_ERROR_CODES:
        return _action(False, "REAUTHORIZATION_REQUIRED")
    if task.retry_not_before is not None and task.retry_not_before > now:
        return _action(False, "RETRY_DELAY_ACTIVE")
    if not getattr(task, "_ui_consistent", False):
        return _action(False, "TASK_INCONSISTENT")
    content = task.platform_content
    account = task.social_account
    if (
        content.status != PlatformContent.Status.APPROVED
        or content.version != task.content_version
        or getattr(task, "_has_newer_content", True)
    ):
        return _action(False, "CONTENT_NOT_CURRENT")
    if getattr(task, "_has_blocking_publish_task", True):
        return _action(False, "DUPLICATE_LIVE_TASK")
    if (
        account.status != SocialAccount.Status.ACTIVE
        or account.publish_mode != SocialAccount.PublishMode.API_AUTO
        or account.organization_id != task.organization_id
        or account.platform_id != task.platform_id
        or AccountCapability.PUBLISH not in resolve_loaded_account_capabilities(account)
    ):
        return _action(False, "ACCOUNT_NOT_READY")
    return _action(True)


def _reconcile_action(task):
    if task.status not in {
        PublishTask.Status.SUBMITTED,
        PublishTask.Status.SUBMISSION_UNKNOWN,
    }:
        return _action(False, "STATUS_NOT_RECONCILABLE")
    _account, _connection, buffer_valid = _buffer_dependencies(task)
    if not buffer_valid:
        return _action(False, "BUFFER_ACCOUNT_REQUIRED")
    if task.status == PublishTask.Status.SUBMITTED:
        valid = type(task.provider_submission_id) is str and bool(task.provider_submission_id.strip())
    elif task.status == PublishTask.Status.SUBMISSION_UNKNOWN:
        fingerprint = task.provider_request_fingerprint
        attempt = _latest_attempt(task)
        valid = (
            type(fingerprint) is str and len(fingerprint) == 64
            and all(character in "0123456789abcdef" for character in fingerprint)
            and task.provider_call_started_at is not None
            and attempt is not None
            and attempt.status == PublishAttempt.Status.SUBMISSION_UNKNOWN
            and attempt.provider_request_fingerprint == fingerprint
        )
    return _action(valid, "RECONCILIATION_EVIDENCE_MISSING")


def publish_task_ui_contract(task, *, now=None):
    """Return UI hints only. Mutation endpoints continue to lock and revalidate."""
    from .services import publish_task_is_consistent

    now = now or timezone.now()
    task._ui_consistent = publish_task_is_consistent(task)
    audit = _latest_audit(task)
    attempt = _latest_attempt(task)
    account, connection, buffer_valid = _buffer_dependencies(task)
    try:
        task.published_post
    except PublishedPost.DoesNotExist:
        has_post = False
    else:
        has_post = True
    snapshot_valid = bool(
        audit is not None
        and audit.organization_id == task.organization_id
        and task.last_reconciled_at == audit.finished_at
        and task.reconciliation_error_code == audit.safe_error_code
        and buffer_valid
        and account.updated_at <= audit.finished_at
        and connection.updated_at <= audit.finished_at
    )
    strict_no_match = bool(
        buffer_valid
        and task.status == PublishTask.Status.NEEDS_ATTENTION
        and attempt is not None
        and attempt.status == PublishAttempt.Status.NEEDS_ATTENTION
        and strict_no_post_evidence(
            task, audit, account, connection, now,
            published_post_exists=has_post,
        )
    )
    can_confirm_published = bool(
        buffer_valid
        and task.status == PublishTask.Status.NEEDS_ATTENTION
        and attempt is not None
        and attempt.status == PublishAttempt.Status.NEEDS_ATTENTION
    )
    safe_code = audit.safe_error_code if audit and audit.safe_error_code in SAFE_EVIDENCE_CODES else ""
    ambiguous = safe_code == "BUFFER_RECONCILIATION_AMBIGUOUS"
    evidence = {
        "latest_outcome": audit.result if audit and audit.result in SAFE_EVIDENCE_RESULTS else None,
        "candidate_count": audit.candidate_count if audit is not None else None,
        "query_window_end": audit.query_window_end if audit is not None else None,
        "query_window_ended": bool(audit and audit.query_window_end and audit.query_window_end <= now),
        "ambiguous": ambiguous,
        "truncated": bool(ambiguous and audit.candidate_count <= 1),
        "snapshot_valid": snapshot_valid,
        "observed_at": audit.finished_at if audit is not None else None,
    }
    actions = {
        "retry": _retry_action(task, now),
        "reconcile": _reconcile_action(task),
        "confirm_published": _action(can_confirm_published, "STATUS_NOT_RESOLVABLE"),
        "confirm_not_published": _action(strict_no_match, "STRICT_NO_MATCH_REQUIRED"),
    }
    return {"allowed_actions": actions, "resolution_evidence": evidence}
