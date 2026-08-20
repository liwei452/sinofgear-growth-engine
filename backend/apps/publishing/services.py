import hashlib
import json
import logging
import uuid
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.utils import timezone

from apps.content.models import PlatformContent
from apps.content.services import content_is_consistent
from apps.content.services import transition_content
from apps.campaigns.models import ContentBriefPlatform
from apps.platforms.capabilities import resolve_account_capabilities
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ConnectorCredential, PlatformCapability, SocialAccount

from integrations.platforms.base import (
    ConnectorConfigurationRequired,
    OfficialPublishRequest,
    PublishRequest,
    PublishResult,
)
from integrations.platforms.runtime import get_social_provider_runtime


from integrations.platforms.registry import get_connector
from integrations.platforms.registry import CONNECTOR_FACTORIES

from .models import PublishAttempt, PublishedPost, PublishTask, publishing_writes
from .publish_payload import PublishPayloadError, build_publish_payload


logger = logging.getLogger(__name__)


MAX_SCHEDULE_AHEAD = timedelta(days=366)
MAX_PUBLISH_ATTEMPTS = 10
PUBLISH_LEASE_SECONDS = 300
SAFE_PUBLISH_ERRORS = {
    "PUBLISH_NOT_ELIGIBLE": {
        "code": "PUBLISH_NOT_ELIGIBLE",
        "message": "Publish eligibility changed before execution.",
    },
    "RATE_LIMITED": {
        "code": "RATE_LIMITED", "message": "Provider rate limit reached.",
    },
    "VALIDATION_REJECTED": {
        "code": "VALIDATION_REJECTED", "message": "Publish payload was rejected.",
    },
    "REAUTHORIZATION_REQUIRED": {
        "code": "REAUTHORIZATION_REQUIRED", "message": "Provider authorization must be renewed.",
    },
    "BUFFER_PROVIDER_CAPACITY": {
        "code": "BUFFER_PROVIDER_CAPACITY", "message": "Buffer provider capacity was reached.",
    },
    "BUFFER_CHANNEL_NOT_FOUND": {
        "code": "BUFFER_CHANNEL_NOT_FOUND", "message": "Buffer channel was not found.",
    },
    "TOKEN_EXPIRED": {
        "code": "TOKEN_EXPIRED", "message": "Account authorization has expired.",
    },
    "PROVIDER_ERROR": {
        "code": "PROVIDER_ERROR", "message": "Provider rejected the publish request.",
    },
    "PUBLISH_FINALIZE_ERROR": {
        "code": "PUBLISH_FINALIZE_ERROR",
        "message": "Publishing result could not be finalized.",
    },
    "STALE_WORKER": {
        "code": "STALE_WORKER",
        "message": "Worker lease expired without heartbeat.",
    },
    "OUTCOME_UNKNOWN": {
        "code": "OUTCOME_UNKNOWN",
        "message": "Provider outcome could not be determined.",
    },
}


class PublishingConflict(ValueError):
    pass


def _attempt_history_is_consistent(task, post):
    attempts = getattr(task, "_safe_attempts", None)
    if attempts is None:
        attempts = list(task.attempts.order_by("-number")[:MAX_PUBLISH_ATTEMPTS + 1])
    attempts = sorted(attempts, key=lambda attempt: attempt.number)
    if len(attempts) > MAX_PUBLISH_ATTEMPTS:
        return False
    if [attempt.number for attempt in attempts] != list(range(1, task.attempt_number + 1)):
        return False
    previous = None
    for attempt in attempts:
        if (
            attempt.organization_id != task.organization_id
            or attempt.task_id != task.id
            or attempt.status not in PublishAttempt.Status.values
            or attempt.request_fingerprint != task.request_fingerprint
        ):
            return False
        if attempt.finished_at is not None and attempt.finished_at < attempt.started_at:
            return False
        if attempt.provider_call_started_at is not None and (
            attempt.provider_call_started_at < attempt.started_at
            or (
                attempt.finished_at is not None
                and attempt.provider_call_started_at > attempt.finished_at
            )
        ):
            return False
        if (
            previous is not None
            and (
                previous.finished_at is None
                or previous.finished_at > attempt.started_at
                or (
                    previous.retry_at is not None
                    and previous.retry_at > attempt.started_at
                )
                or (
                    previous.status == PublishAttempt.Status.FAILED
                    and previous.outcome == "TOKEN_EXPIRED"
                )
            )
        ):
            return False
        if attempt.status == PublishAttempt.Status.RUNNING and any(
            (
                attempt.outcome, attempt.error, attempt.retry_at,
                attempt.finished_at, attempt.external_id,
            )
        ):
            return False
        if attempt.status == PublishAttempt.Status.SUCCEEDED and not (
            attempt.outcome == "SUCCEEDED"
            and attempt.error is None
            and attempt.retry_at is None
            and attempt.external_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.status == PublishAttempt.Status.FAILED and not (
            _safe_error_is_exact(attempt.error)
            and attempt.outcome == attempt.error["code"]
            and (
                (attempt.error["code"] == "RATE_LIMITED" and attempt.retry_at is not None)
                or (attempt.error["code"] != "RATE_LIMITED" and attempt.retry_at is None)
            )
            and not attempt.external_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.status == PublishAttempt.Status.CANCELED and not (
            attempt.outcome == "CANCELED"
            and attempt.error is None
            and attempt.retry_at is None
            and not attempt.external_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.status == PublishAttempt.Status.STALE and not (
            not attempt.outcome
            and attempt.error is None
            and attempt.retry_at is None
            and not attempt.external_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.status == PublishAttempt.Status.SUBMITTED and not (
            attempt.outcome == "SUBMITTED"
            and attempt.error is None
            and attempt.retry_at is None
            and attempt.provider_submission_id
            and not attempt.external_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.status == PublishAttempt.Status.SUBMISSION_UNKNOWN and not (
            attempt.outcome == "OUTCOME_UNKNOWN"
            and _safe_error_is_exact(attempt.error)
            and attempt.error["code"] == "OUTCOME_UNKNOWN"
            and attempt.retry_at is None
            and not attempt.external_id
            and not attempt.provider_submission_id
            and attempt.finished_at is not None
        ):
            return False
        if attempt.retry_at is not None and attempt.retry_at < attempt.finished_at:
            return False
        previous = attempt
    latest = attempts[-1] if attempts else None
    if any(
        attempt.status in {
            PublishAttempt.Status.RUNNING,
            PublishAttempt.Status.SUBMITTED,
            PublishAttempt.Status.SUBMISSION_UNKNOWN,
            PublishAttempt.Status.SUCCEEDED,
            PublishAttempt.Status.CANCELED,
        }
        for attempt in attempts[:-1]
    ):
        return False
    if post is not None and (
        latest is None or post.attempt_id != latest.id
        or latest.status != PublishAttempt.Status.SUCCEEDED
    ):
        return False
    return True


def _safe_error_is_exact(value):
    return (
        isinstance(value, dict)
        and value.get("code") in SAFE_PUBLISH_ERRORS
        and value == SAFE_PUBLISH_ERRORS[value["code"]]
    )


def publish_task_is_consistent(task):
    try:
        content = task.platform_content
        selected = getattr(task, "_selected_platform", None)
        if selected is not None:
            content._selected_platform = selected
        scheduled_at = (
            task.scheduled_at.astimezone(dt_timezone.utc) if task.scheduled_at else None
        )
        fingerprint = _fingerprint(
            content=content,
            account=task.social_account,
            scheduled_at=scheduled_at,
            timezone_name=_canonical_timezone(task.requested_timezone),
            connector_code=task.connector_code,
        )
        try:
            post = task.published_post
        except ObjectDoesNotExist:
            post = None
        base = (
            task.status in PublishTask.Status.values
            and task.organization_id == content.organization_id
            and task.organization_id == task.social_account.organization_id
            and task.platform_id == content.platform_id == task.social_account.platform_id
            and task.content_version == content.version
            and task.connector_code in CONNECTOR_FACTORIES
            and task.request_fingerprint == fingerprint
            and validate_idempotency_key(task.idempotency_key) == task.idempotency_key
            and content_is_consistent(content)
            and _attempt_history_is_consistent(task, post)
        )
        if not base:
            return False
        if task.status == PublishTask.Status.SCHEDULED:
            return (
                task.scheduled_at is not None
                and task.claim_token is None
                and task.attempt_number == 0
                and task.started_at is None
                and task.finished_at is None
                and task.canceled_at is None
                and task.last_error is None
                and task.retry_not_before is None
                and task.provider_call_started_at is None
                and post is None
            )
        attempts = getattr(task, "_safe_attempts", None)
        if attempts is None:
            attempts = list(
                task.attempts.order_by("-number")[:MAX_PUBLISH_ATTEMPTS + 1]
            )
        attempts = sorted(attempts, key=lambda attempt: attempt.number)
        latest = attempts[-1] if attempts else None
        if task.status == PublishTask.Status.RUNNING:
            return (
                task.claim_token is not None and task.attempt_number > 0
                and task.started_at is not None and task.finished_at is None
                and task.canceled_at is None and task.last_error is None
                and task.retry_not_before is None and post is None
                and latest is not None
                and latest.status == PublishAttempt.Status.RUNNING
                and latest.claim_token == task.claim_token
                and latest.started_at == task.started_at
                and task.provider_call_started_at == latest.provider_call_started_at
            )
        if task.status == PublishTask.Status.SUCCEEDED:
            return (
                content.status == PlatformContent.Status.PUBLISHED
                and task.claim_token is None and task.started_at is not None
                and task.finished_at is not None and task.canceled_at is None
                and task.last_error is None and task.retry_not_before is None
                and post is not None and latest is not None
                and latest.status == PublishAttempt.Status.SUCCEEDED
                and latest.started_at == task.started_at
                and latest.finished_at == task.finished_at == post.published_at
                and post.organization_id == task.organization_id
                and post.platform_content_id == task.platform_content_id
                and post.social_account_id == task.social_account_id
                and post.attempt_id == latest.id
                and post.external_id == latest.external_id
                and task.provider_call_started_at is not None
                and task.provider_call_started_at == latest.provider_call_started_at
            )
        if task.status == PublishTask.Status.SUBMITTED:
            return (
                content.status == PlatformContent.Status.APPROVED
                and task.claim_token is None and task.started_at is not None
                and task.finished_at is not None and task.canceled_at is None
                and task.last_error is None and task.retry_not_before is None
                and task.provider_submission_id
                and post is None and latest is not None
                and latest.status == PublishAttempt.Status.SUBMITTED
                and latest.started_at == task.started_at
                and latest.finished_at == task.finished_at
                and latest.provider_submission_id == task.provider_submission_id
                and task.provider_call_started_at is not None
                and task.provider_call_started_at == latest.provider_call_started_at
            )
        if task.status == PublishTask.Status.SUBMISSION_UNKNOWN:
            return (
                content.status == PlatformContent.Status.APPROVED
                and task.claim_token is None and task.started_at is not None
                and task.finished_at is not None and task.canceled_at is None
                and _safe_error_is_exact(task.last_error)
                and task.last_error["code"] == "OUTCOME_UNKNOWN"
                and task.retry_not_before is None
                and not task.provider_submission_id
                and post is None and latest is not None
                and latest.status == PublishAttempt.Status.SUBMISSION_UNKNOWN
                and latest.started_at == task.started_at
                and latest.finished_at == task.finished_at
                and latest.error == task.last_error
                and task.provider_call_started_at is not None
                and task.provider_call_started_at == latest.provider_call_started_at
            )
        if task.status == PublishTask.Status.FAILED:
            return (
                task.claim_token is None and task.started_at is not None
                and task.finished_at is not None and task.canceled_at is None
                and _safe_error_is_exact(task.last_error)
                and latest is not None and latest.status == PublishAttempt.Status.FAILED
                and latest.started_at == task.started_at
                and latest.finished_at == task.finished_at
                and latest.error == task.last_error
                and latest.retry_at == task.retry_not_before
                and task.provider_call_started_at == latest.provider_call_started_at
                and post is None
            )
        if task.status == PublishTask.Status.CANCELED:
            base_canceled = (
                task.claim_token is None and task.canceled_at is not None
                and task.finished_at == task.canceled_at
                and task.last_error is None and task.retry_not_before is None
                and post is None
            )
            if not base_canceled:
                return False
            if task.attempt_number == 0:
                return task.started_at is None and latest is None
            return (
                latest is not None
                and latest.status == PublishAttempt.Status.CANCELED
                and latest.started_at == task.started_at
                and latest.finished_at == task.finished_at
                and task.provider_call_started_at == latest.provider_call_started_at
            )
        if task.status != PublishTask.Status.QUEUED:
            return False
        base_queued = (
            task.claim_token is None and task.finished_at is None
            and task.canceled_at is None and task.last_error is None
            and task.retry_not_before is None and post is None
        )
        if not base_queued:
            return False
        if task.attempt_number == 0:
            return (
                task.started_at is None and latest is None
                and task.provider_call_started_at is None
            )
        return (
            latest is not None and latest.status == PublishAttempt.Status.FAILED
            and task.started_at == latest.started_at
            and task.provider_call_started_at is None
        )
    except (AttributeError, KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False


def publish_task_consistency_queryset(organization):
    """Load every relation used by publish_task_is_consistent in fixed queries."""
    return (
        PublishTask.objects.filter(organization=organization)
        .select_related(
            "platform_content__platform",
            "platform_content__master_content__brief",
            "platform_content__master_content__generation_job",
            "platform_content__master_content__ai_run",
            "platform_content__master_content__previous_version",
            "platform_content__previous_version",
            "social_account__platform", "social_account__credential", "platform",
            "published_post__attempt",
        )
        .prefetch_related(
            Prefetch(
                "attempts",
                queryset=PublishAttempt.objects.order_by("-number")[
                    :MAX_PUBLISH_ATTEMPTS + 1
                ],
                to_attr="_safe_attempts",
            )
        )
        .annotate(
            _selected_platform=Exists(
                ContentBriefPlatform.objects.filter(
                    brief_id=OuterRef("platform_content__master_content__brief_id"),
                    platform_id=OuterRef("platform_id"),
                )
            )
        )
    )


def consistent_publish_task_ids(*, organization, task_ids):
    """Return IDs whose fully loaded tasks pass the canonical Task11 validator."""
    tasks = publish_task_consistency_queryset(organization).filter(pk__in=tuple(task_ids))
    return frozenset(task.id for task in tasks if publish_task_is_consistent(task))


def _canonical_timezone(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 64:
        raise PublishingConflict("A valid IANA timezone is required.")
    try:
        return ZoneInfo(name.strip()).key
    except ZoneInfoNotFoundError as exc:
        raise PublishingConflict("A valid IANA timezone is required.") from exc


def _canonical_schedule(value):
    if value is None:
        return None
    if not timezone.is_aware(value):
        raise PublishingConflict("Scheduled time must be timezone-aware.")
    value = value.astimezone(dt_timezone.utc)
    now = timezone.now()
    if value <= now or value > now + MAX_SCHEDULE_AHEAD:
        raise PublishingConflict("Scheduled time must be in the future within 366 days.")
    return value


def _fingerprint(*, content, account, scheduled_at, timezone_name, connector_code):
    request = {
        "account_id": str(account.id),
        "connector_code": connector_code,
        "content_id": str(content.id),
        "content_version": content.version,
        "platform_id": str(content.platform_id),
        "scheduled_at": scheduled_at.isoformat().replace("+00:00", "Z")
        if scheduled_at else None,
        "timezone": timezone_name,
    }
    raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_idempotency_key(value):
    if (
        not isinstance(value, str)
        or not (value := value.strip())
        or len(value) > 128
        or any(ord(character) < 33 or ord(character) > 126 for character in value)
    ):
        raise PublishingConflict("Idempotency-Key must be 1-128 visible ASCII characters.")
    return value


@transaction.atomic
def create_publish_task(
    *, content, account, idempotency_key, actor=None, scheduled_at=None,
    timezone_name="UTC", connector_code="mock",
):
    key = validate_idempotency_key(idempotency_key)
    timezone_name = _canonical_timezone(timezone_name)
    scheduled_at = _canonical_schedule(scheduled_at)
    fingerprint = _fingerprint(
        content=content, account=account, scheduled_at=scheduled_at,
        timezone_name=timezone_name, connector_code=connector_code,
    )
    existing = PublishTask.objects.filter(
        organization_id=content.organization_id, idempotency_key=key
    ).first()
    if existing:
        if not publish_task_is_consistent(existing):
            raise PublishingConflict("Existing publish task is inconsistent.")
        if existing.request_fingerprint != fingerprint:
            raise PublishingConflict("Idempotency-Key already has a different request.")
        return existing

    locked_content = PlatformContent.objects.select_for_update().select_related(
        "platform", "master_content__brief", "master_content__generation_job",
        "master_content__ai_run", "master_content__previous_version", "previous_version",
    ).get(pk=content.pk)
    locked_account = SocialAccount.objects.select_for_update().select_related(
        "platform", "credential"
    ).get(pk=account.pk)
    if not content_is_consistent(locked_content):
        raise PublishingConflict("Platform content provenance is inconsistent.")
    if locked_content.status != PlatformContent.Status.APPROVED:
        raise PublishingConflict("Platform content must be APPROVED.")
    if PlatformContent.objects.filter(previous_version=locked_content).exists():
        raise PublishingConflict("Platform content must be the current lineage head.")
    if locked_account.status != SocialAccount.Status.ACTIVE:
        raise PublishingConflict("Social account must be ACTIVE.")
    if locked_account.organization_id != locked_content.organization_id:
        raise PublishingConflict("Content and account organization must match.")
    if locked_account.platform_id != locked_content.platform_id:
        raise PublishingConflict("Content and account platform must match.")
    if locked_account.publish_mode != SocialAccount.PublishMode.API_AUTO:
        raise PublishingConflict("Account publish mode does not support automatic publishing.")
    if (
        locked_account.credential
        and locked_account.credential.expires_at
        and locked_account.credential.expires_at <= timezone.now()
    ):
        raise PublishingConflict("Account connector credential has expired.")
    if AccountCapability.PUBLISH not in resolve_account_capabilities(locked_account.id):
        raise PublishingConflict("Account connector does not have publishing capability.")
    limit = getattr(locked_content.organization, "daily_publish_limit", None)
    if limit:
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = PublishedPost.objects.filter(
            organization_id=locked_content.organization_id,
            published_at__gte=start,
        ).count()
        pending = PublishTask.objects.filter(
            organization_id=locked_content.organization_id,
            status__in=[
                PublishTask.Status.SCHEDULED,
                PublishTask.Status.QUEUED,
                PublishTask.Status.RUNNING,
                PublishTask.Status.SUBMITTED,
                PublishTask.Status.SUBMISSION_UNKNOWN,
            ],
        ).count()
        if published_today + pending >= limit:
            raise PublishingConflict("Daily publishing limit reached.")
    status = PublishTask.Status.SCHEDULED if scheduled_at else PublishTask.Status.QUEUED
    try:
        with transaction.atomic():
            with publishing_writes():
                task = PublishTask.objects.create(
                    organization=locked_content.organization,
                    platform_content=locked_content,
                    content_version=locked_content.version,
                    social_account=locked_account,
                    platform=locked_content.platform,
                    connector_code=connector_code,
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                    status=status,
                    scheduled_at=scheduled_at,
                    requested_timezone=timezone_name,
                    created_by=actor,
                )
    except IntegrityError:
        existing = PublishTask.objects.get(
            organization=locked_content.organization, idempotency_key=key
        )
        if not publish_task_is_consistent(existing):
            raise PublishingConflict("Existing publish task is inconsistent.") from None
        if existing.request_fingerprint != fingerprint:
            raise PublishingConflict(
                "Idempotency-Key already has a different request."
            ) from None
        return existing
    if status == PublishTask.Status.QUEUED:
        from .tasks import run_publish_task

        transaction.on_commit(lambda: run_publish_task.delay(str(task.id)))
    return task


@transaction.atomic
def claim_publish_task(task_id=None):
    queryset = PublishTask.objects.select_for_update(skip_locked=True).filter(
        status=PublishTask.Status.QUEUED
    ).filter(Q(retry_not_before__isnull=True) | Q(retry_not_before__lte=timezone.now()))
    if task_id is not None:
        queryset = queryset.filter(pk=task_id)
    task = queryset.order_by("created_at", "id").first()
    if task is None:
        return None
    token = uuid.uuid4()
    now = timezone.now()
    content = PlatformContent.objects.select_for_update().select_related(
        "platform", "master_content__brief", "master_content__generation_job",
        "master_content__ai_run", "master_content__previous_version", "previous_version",
    ).get(pk=task.platform_content_id)
    account = SocialAccount.objects.select_for_update().select_related(
        "platform", "provider_connection",
    ).get(pk=task.social_account_id)
    credential = None
    if account.credential_id:
        credential = ConnectorCredential.objects.select_for_update().filter(
            pk=account.credential_id
        ).first()
    list(
        PlatformCapability.objects.select_for_update().filter(
            platform_id=account.platform_id
        ).values_list("id", flat=True)
    )
    task._state.fields_cache["platform_content"] = content
    task._state.fields_cache["social_account"] = account
    direct_eligible = (
        account.provider == SocialAccount.Provider.DIRECT
        and credential is not None
        and credential.organization_id == account.organization_id
        and credential.platform_id == account.platform_id
        and (credential.expires_at is None or credential.expires_at > now)
    )
    provider_connection = account.provider_connection
    buffer_eligible = (
        account.provider == SocialAccount.Provider.BUFFER
        and credential is None
        and account.connection_state == SocialAccount.ConnectionState.CONNECTED
        and bool(account.provider_account_id.strip())
        and provider_connection is not None
        and provider_connection.provider == provider_connection.Provider.BUFFER
        and provider_connection.organization_id == account.organization_id
        and provider_connection.connection_state
        == provider_connection.ConnectionState.CONNECTED
        and bool(provider_connection.credential_reference.strip())
    )
    eligible = (
        publish_task_is_consistent(task)
        and content_is_consistent(content)
        and content.status == PlatformContent.Status.APPROVED
        and not PlatformContent.objects.select_for_update().filter(
            previous_version=content
        ).exists()
        and task.organization_id == content.organization_id == account.organization_id
        and task.platform_id == content.platform_id == account.platform_id
        and task.content_version == content.version
        and account.status == SocialAccount.Status.ACTIVE
        and account.publish_mode == SocialAccount.PublishMode.API_AUTO
        and (direct_eligible or buffer_eligible)
        and AccountCapability.PUBLISH in resolve_account_capabilities(account.id)
    )
    if not eligible:
        error = SAFE_PUBLISH_ERRORS["PUBLISH_NOT_ELIGIBLE"]
        task.status = PublishTask.Status.FAILED
        task.claim_token = None
        task.attempt_number += 1
        task.started_at = now
        task.finished_at = now
        task.last_error = error
        task.retry_not_before = None
        with publishing_writes():
            task.save(update_fields=[
                "status", "claim_token", "attempt_number", "started_at",
                "finished_at", "last_error", "retry_not_before", "updated_at",
            ])
            PublishAttempt.objects.create(
                organization=task.organization,
                task=task,
                number=task.attempt_number,
                claim_token=token,
                status=PublishAttempt.Status.FAILED,
                request_fingerprint=task.request_fingerprint,
                outcome=error["code"],
                error=error,
                started_at=now,
                finished_at=now,
            )
        return None
    task.status = PublishTask.Status.RUNNING
    task.claim_token = token
    task.attempt_number += 1
    task.heartbeat_at = now
    task.lease_expires_at = now + timedelta(seconds=PUBLISH_LEASE_SECONDS)
    task.started_at = now
    task.finished_at = None
    task.last_error = None
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "attempt_number", "heartbeat_at",
            "lease_expires_at", "started_at", "finished_at", "last_error", "updated_at",
        ])
        attempt = PublishAttempt.objects.create(
            organization=task.organization,
            task=task,
            number=task.attempt_number,
            claim_token=token,
            status=PublishAttempt.Status.RUNNING,
            request_fingerprint=task.request_fingerprint,
            started_at=now,
        )
    return task, attempt


def _safe_error(result):
    code = result.error_code if result.error_code in SAFE_PUBLISH_ERRORS else "PROVIDER_ERROR"
    return SAFE_PUBLISH_ERRORS[code]


@transaction.atomic
def complete_publish_failure(task_id, claim_token, result):
    task = PublishTask.objects.select_for_update().get(pk=task_id)
    attempt = PublishAttempt.objects.select_for_update().get(
        task=task, claim_token=claim_token
    )
    if task.status != PublishTask.Status.RUNNING or task.claim_token != claim_token:
        if attempt.status == PublishAttempt.Status.RUNNING:
            attempt.status = PublishAttempt.Status.STALE
            attempt.finished_at = timezone.now()
            with publishing_writes():
                attempt.save(update_fields=["status", "finished_at", "updated_at"])
        return task
    now = timezone.now()
    error = _safe_error(result)
    retry_at = (
        now + timedelta(seconds=min(max(result.retry_after_seconds or 60, 1), 3600))
        if error["code"] == "RATE_LIMITED" else None
    )
    task.status = PublishTask.Status.FAILED
    task.claim_token = None
    task.last_error = error
    task.retry_not_before = retry_at
    task.finished_at = now
    attempt.status = PublishAttempt.Status.FAILED
    attempt.outcome = error["code"]
    attempt.error = error
    attempt.retry_at = retry_at
    attempt.finished_at = now
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "last_error", "retry_not_before",
            "finished_at", "updated_at",
        ])
        attempt.save(update_fields=[
            "status", "outcome", "error", "retry_at", "finished_at", "updated_at",
        ])
    return task


@transaction.atomic
def complete_publish_success(task_id, claim_token, result, *, actor=None):
    task = PublishTask.objects.select_for_update().select_related(
        "platform_content"
    ).get(pk=task_id)
    attempt = PublishAttempt.objects.select_for_update().get(
        task=task, claim_token=claim_token
    )
    if task.status != PublishTask.Status.RUNNING or task.claim_token != claim_token:
        if attempt.status == PublishAttempt.Status.RUNNING:
            attempt.status = PublishAttempt.Status.STALE
            attempt.finished_at = timezone.now()
            with publishing_writes():
                attempt.save(update_fields=["status", "finished_at", "updated_at"])
        return None
    if not result.succeeded or not result.external_id or len(result.external_id) > 255:
        raise PublishingConflict("Connector success result is invalid.")
    now = timezone.now()
    with publishing_writes():
        post = PublishedPost.objects.create(
            organization=task.organization,
            task=task,
            attempt=attempt,
            platform_content=task.platform_content,
            social_account=task.social_account,
            external_id=result.external_id,
            published_at=now,
        )
    if task.platform_content.status == PlatformContent.Status.APPROVED:
        transition_content(
            task.platform_content, action="PUBLISH",
            actor=actor or task.created_by, comment="Mock platform publish succeeded.",
        )
    elif task.platform_content.status != PlatformContent.Status.PUBLISHED:
        raise PublishingConflict("Platform content is no longer publishable.")
    task.status = PublishTask.Status.SUCCEEDED
    task.claim_token = None
    task.last_error = None
    task.retry_not_before = None
    task.finished_at = now
    attempt.status = PublishAttempt.Status.SUCCEEDED
    attempt.outcome = "SUCCEEDED"
    attempt.external_id = result.external_id
    attempt.finished_at = now
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "last_error", "retry_not_before",
            "finished_at", "updated_at",
        ])
        attempt.save(update_fields=[
            "status", "outcome", "external_id", "finished_at", "updated_at",
        ])
    return post


def _normalize_submission_id(value) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        return None
    return normalized


def _result_kind(result):
    if getattr(result, "succeeded", False):
        return "succeeded"
    if getattr(result, "submitted", False):
        submission_id = _normalize_submission_id(
            getattr(result, "submission_id", "")
        )
        return "submitted" if submission_id else "unknown"
    if getattr(result, "error_code", "") == "OUTCOME_UNKNOWN":
        return "unknown"
    return "failed"


@transaction.atomic
def complete_publish_submitted(task_id, claim_token, result):
    submission_id = _normalize_submission_id(getattr(result, "submission_id", ""))
    if submission_id is None:
        raise PublishingConflict("Connector submission id is invalid.")
    task = PublishTask.objects.select_for_update().get(pk=task_id)
    attempt = PublishAttempt.objects.select_for_update().get(
        task=task, claim_token=claim_token
    )
    if task.status != PublishTask.Status.RUNNING or task.claim_token != claim_token:
        if attempt.status == PublishAttempt.Status.RUNNING:
            attempt.status = PublishAttempt.Status.STALE
            attempt.finished_at = timezone.now()
            with publishing_writes():
                attempt.save(update_fields=["status", "finished_at", "updated_at"])
        return task
    now = timezone.now()
    task.status = PublishTask.Status.SUBMITTED
    task.claim_token = None
    task.last_error = None
    task.retry_not_before = None
    task.provider_submission_id = submission_id
    task.finished_at = now
    attempt.status = PublishAttempt.Status.SUBMITTED
    attempt.outcome = "SUBMITTED"
    attempt.error = None
    attempt.retry_at = None
    attempt.provider_submission_id = submission_id
    attempt.finished_at = now
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "last_error", "retry_not_before",
            "provider_submission_id", "finished_at", "updated_at",
        ])
        attempt.save(update_fields=[
            "status", "outcome", "error", "retry_at",
            "provider_submission_id", "finished_at", "updated_at",
        ])
    return task


@transaction.atomic
def complete_publish_unknown(task_id, claim_token, result):
    del result
    task = PublishTask.objects.select_for_update().get(pk=task_id)
    attempt = PublishAttempt.objects.select_for_update().get(
        task=task, claim_token=claim_token
    )
    if task.status != PublishTask.Status.RUNNING or task.claim_token != claim_token:
        if attempt.status == PublishAttempt.Status.RUNNING:
            attempt.status = PublishAttempt.Status.STALE
            attempt.finished_at = timezone.now()
            with publishing_writes():
                attempt.save(update_fields=["status", "finished_at", "updated_at"])
        return task
    now = timezone.now()
    error = SAFE_PUBLISH_ERRORS["OUTCOME_UNKNOWN"]
    task.status = PublishTask.Status.SUBMISSION_UNKNOWN
    task.claim_token = None
    task.last_error = error
    task.retry_not_before = None
    task.finished_at = now
    attempt.status = PublishAttempt.Status.SUBMISSION_UNKNOWN
    attempt.outcome = "OUTCOME_UNKNOWN"
    attempt.error = error
    attempt.retry_at = None
    attempt.finished_at = now
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "last_error", "retry_not_before",
            "finished_at", "updated_at",
        ])
        attempt.save(update_fields=[
            "status", "outcome", "error", "retry_at", "finished_at", "updated_at",
        ])
    return task


@transaction.atomic
def heartbeat_publish_task(task_id, *, claim_token) -> PublishTask:
    task = PublishTask.objects.select_for_update().get(pk=task_id)
    if task.status != PublishTask.Status.RUNNING or task.claim_token != claim_token:
        return task
    now = timezone.now()
    task.heartbeat_at = now
    task.lease_expires_at = now + timedelta(seconds=PUBLISH_LEASE_SECONDS)
    with publishing_writes():
        task.save(update_fields=["heartbeat_at", "lease_expires_at", "updated_at"])
    return task


@transaction.atomic
def reap_stale_publish_tasks(*, now=None) -> int:
    now = now or timezone.now()
    stale = list(
        PublishTask.objects.select_for_update(skip_locked=True).filter(
            status=PublishTask.Status.RUNNING,
            lease_expires_at__lt=now,
        )
    )
    for task in stale:
        token = task.claim_token
        provider_called = task.provider_call_started_at is not None
        if provider_called:
            error = SAFE_PUBLISH_ERRORS["OUTCOME_UNKNOWN"]
            task.status = PublishTask.Status.SUBMISSION_UNKNOWN
        else:
            error = SAFE_PUBLISH_ERRORS["STALE_WORKER"]
            task.status = PublishTask.Status.FAILED
        task.last_error = error
        task.finished_at = now
        task.claim_token = None
        with publishing_writes():
            task.save(update_fields=[
                "status", "last_error", "finished_at", "claim_token", "updated_at",
            ])
        if token:
            attempt = PublishAttempt.objects.filter(claim_token=token).first()
            if attempt is not None and attempt.status == PublishAttempt.Status.RUNNING:
                if provider_called:
                    attempt.status = PublishAttempt.Status.SUBMISSION_UNKNOWN
                    attempt.outcome = "OUTCOME_UNKNOWN"
                else:
                    attempt.status = PublishAttempt.Status.FAILED
                    attempt.outcome = "STALE_WORKER"
                attempt.error = error
                attempt.finished_at = now
                with publishing_writes():
                    attempt.save(update_fields=[
                        "status", "outcome", "error", "finished_at", "updated_at",
                    ])
    return len(stale)


def _build_mock_call(task, attempt_number):
    request = PublishRequest(
        task_id=task.id,
        attempt_number=attempt_number,
        platform_code=task.platform.code,
        account_external_id=task.social_account.external_id,
        content_payload=task.platform_content.payload,
        scheduled_at=task.scheduled_at,
    )
    return get_connector(task.connector_code, task.social_account), request


def _prepare_tracking_url(task) -> str | None:
    from .pre_publish import build_short_link_url, prepare_pre_publish_short_link

    try:
        short_link = prepare_pre_publish_short_link(
            platform_content=task.platform_content,
            actor=task.created_by,
        )
        return build_short_link_url(short_link)
    except Exception:
        logger.exception("Pre-publish tracking link preparation failed.")
        return None


def _resolve_media(task):
    try:
        from .pre_publish import resolve_media

        return resolve_media(task.platform_content)
    except Exception:
        logger.exception("Media URL resolution failed.")
        return None


def _build_official_call(task):
    content_payload = task.platform_content.payload or {}
    media = _resolve_media(task)
    payload = build_publish_payload(
        platform_code=task.platform.code,
        content_payload=content_payload,
        media_url=media.url if media else None,
        media_kind=media.kind if media else "VIDEO",
        tracking_url=_prepare_tracking_url(task),
    )
    consent = content_payload.get("consent")
    if not isinstance(consent, dict):
        consent = {}
    connector = get_social_provider_runtime().connector_registry.resolve(task.social_account)
    if getattr(
        task.social_account, "provider", SocialAccount.Provider.DIRECT
    ) == SocialAccount.Provider.BUFFER:
        connection = getattr(task.social_account, "provider_connection", None)
        credential_reference = connection.credential_reference if connection else ""
        provider_account_id = task.social_account.provider_account_id
    else:
        credential_reference = (
            task.social_account.credential.secret_reference
            if task.social_account.credential else ""
        )
        provider_account_id = ""
    return connector, OfficialPublishRequest(
        channel=task.platform.code,
        account_external_id=task.social_account.external_id,
        provider_account_id=provider_account_id,
        credential_reference=credential_reference,
        payload=payload,
        idempotency_key=str(task.id),
        consent=consent,
    )


@transaction.atomic
def _mark_provider_call_started(task, attempt):
    now = timezone.now()
    task.provider_call_started_at = now
    attempt.provider_call_started_at = now
    with publishing_writes():
        task.save(update_fields=["provider_call_started_at", "updated_at"])
        attempt.save(update_fields=["provider_call_started_at", "updated_at"])


def _associate_pre_publish_tracking(task, post) -> None:
    from apps.tracking.models import TrackingLink, tracking_writes

    try:
        link = TrackingLink.objects.filter(
            organization=task.organization,
            idempotency_key=f"pre-publish:{task.platform_content_id}",
            published_post__isnull=True,
        ).first()
        if link is None:
            return
        with tracking_writes():
            link.published_post = post
            link.save(update_fields=["published_post", "updated_at"])
    except Exception:
        logger.exception("Pre-publish tracking association failed.")


def execute_publish_task(task_id):
    existing = PublishedPost.objects.filter(task_id=task_id).first()
    if existing:
        return existing
    claimed = claim_publish_task(task_id)
    if claimed is None:
        return PublishedPost.objects.filter(task_id=task_id).first()
    task, attempt = claimed
    task = PublishTask.objects.select_related(
        "platform", "platform_content", "social_account", "social_account__credential",
        "social_account__provider_connection",
    ).get(pk=task.pk)

    metadata = task.social_account.connector_metadata if isinstance(
        task.social_account.connector_metadata, dict
    ) else {}
    connection_kind = metadata.get("connection_kind")
    if not connection_kind and metadata.get("fixture") == "phase-a-e2e":
        connection_kind = "demo_fake"

    try:
        if task.social_account.provider == SocialAccount.Provider.BUFFER:
            connector, request = _build_official_call(task)
        elif connection_kind == "official_oauth":
            connector, request = _build_official_call(task)
        elif connection_kind == "demo_fake" or getattr(settings, "PUBLISHING_MOCK_ENABLED", False):
            connector, request = _build_mock_call(task, attempt.number)
        else:
            complete_publish_failure(
                task.id, attempt.claim_token,
                PublishResult(
                    succeeded=False,
                    error_code="PUBLISH_NOT_ELIGIBLE",
                    error_message="Social account is not connected via official OAuth.",
                ),
            )
            return None
    except PublishPayloadError as exc:
        complete_publish_failure(
            task.id, attempt.claim_token,
            PublishResult(succeeded=False, error_code="VALIDATION_REJECTED", error_message=str(exc)),
        )
        return None
    except ConnectorConfigurationRequired:
        complete_publish_failure(
            task.id, attempt.claim_token,
            PublishResult(succeeded=False, error_code="PUBLISH_NOT_ELIGIBLE"),
        )
        return None
    except Exception:
        logger.exception("Publishing preparation failed.")
        complete_publish_failure(
            task.id, attempt.claim_token,
            PublishResult(
                succeeded=False, error_code="PROVIDER_ERROR",
                error_message="Publishing preparation failed.",
            ),
        )
        return None

    _mark_provider_call_started(task, attempt)

    try:
        result = connector.publish(request)
    except (TimeoutError, ConnectionError, OSError):
        logger.exception("Provider publish outcome is unknown.")
        result = PublishResult(
            succeeded=False,
            error_code="OUTCOME_UNKNOWN",
            error_message="Provider publish outcome is unknown.",
        )
    except Exception:
        logger.exception("Provider rejected the publish request.")
        result = PublishResult(
            succeeded=False, error_code="PROVIDER_ERROR",
            error_message="Provider rejected the publish request.",
        )

    kind = _result_kind(result)
    if kind == "succeeded":
        try:
            post = complete_publish_success(
                task.id, attempt.claim_token, result, actor=task.created_by
            )
        except Exception:
            logger.exception("Publish finalization failed.")
            complete_publish_failure(
                task.id, attempt.claim_token,
                PublishResult(succeeded=False, error_code="PUBLISH_FINALIZE_ERROR"),
            )
            return None
        _associate_pre_publish_tracking(task, post)
        return post
    if kind == "submitted":
        complete_publish_submitted(task.id, attempt.claim_token, result)
        return None
    if kind == "unknown":
        complete_publish_unknown(task.id, attempt.claim_token, result)
        return None
    complete_publish_failure(task.id, attempt.claim_token, result)
    return None


@transaction.atomic
def cancel_publish_task(task, *, actor=None):
    del actor
    task = PublishTask.objects.select_for_update().get(pk=task.pk)
    if task.status == PublishTask.Status.CANCELED:
        return task
    if task.status not in {
        PublishTask.Status.SCHEDULED, PublishTask.Status.QUEUED,
        PublishTask.Status.RUNNING,
    }:
        raise PublishingConflict("Only active publish tasks can be canceled.")
    now = timezone.now()
    token = task.claim_token
    task.status = PublishTask.Status.CANCELED
    task.claim_token = None
    task.canceled_at = now
    task.finished_at = now
    with publishing_writes():
        task.save(update_fields=[
            "status", "claim_token", "canceled_at", "finished_at", "updated_at",
        ])
        if token:
            attempt = PublishAttempt.objects.select_for_update().get(
                task=task, claim_token=token
            )
            attempt.status = PublishAttempt.Status.CANCELED
            attempt.outcome = "CANCELED"
            attempt.finished_at = now
            attempt.save(update_fields=[
                "status", "outcome", "finished_at", "updated_at",
            ])
    return task


@transaction.atomic
def retry_publish_task(task, *, actor=None):
    del actor
    task = PublishTask.objects.select_for_update().get(pk=task.pk)
    if task.status in {
        PublishTask.Status.SUBMITTED, PublishTask.Status.SUBMISSION_UNKNOWN,
    }:
        raise PublishingConflict(
            "Submitted or unknown-outcome tasks require reconciliation, not retry."
        )
    if task.status != PublishTask.Status.FAILED:
        raise PublishingConflict("Only failed publish tasks can be retried.")
    if task.attempt_number >= MAX_PUBLISH_ATTEMPTS:
        raise PublishingConflict("Publish attempt limit has been reached.")
    if (task.last_error or {}).get("code") == "TOKEN_EXPIRED":
        raise PublishingConflict("Expired account token requires reauthorization before retry.")
    if task.retry_not_before and task.retry_not_before > timezone.now():
        raise PublishingConflict("Rate-limited task is not ready to retry.")
    task.status = PublishTask.Status.QUEUED
    task.last_error = None
    task.retry_not_before = None
    task.finished_at = None
    task.provider_call_started_at = None
    with publishing_writes():
        task.save(update_fields=[
            "status", "last_error", "retry_not_before", "finished_at",
            "provider_call_started_at", "updated_at",
        ])
    from .tasks import run_publish_task

    transaction.on_commit(lambda: run_publish_task.delay(str(task.id)))
    return task


@transaction.atomic
def run_publish_task_now(task, *, actor=None):
    """Queue one explicitly selected scheduled task, regardless of its future slot."""
    del actor
    task = PublishTask.objects.select_for_update().get(pk=task.pk)
    if task.status != PublishTask.Status.SCHEDULED:
        raise PublishingConflict("Only scheduled publish tasks can be run now.")
    task.status = PublishTask.Status.QUEUED
    with publishing_writes():
        task.save(update_fields=["status", "updated_at"])
    from .tasks import run_publish_task

    transaction.on_commit(lambda: run_publish_task.delay(str(task.id)))
    return task


@transaction.atomic
def enqueue_due_publish_tasks(*, limit=100):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("Queue limit must be an integer from 1 to 500.")
    tasks = list(
        PublishTask.objects.select_for_update(skip_locked=True)
        .filter(status=PublishTask.Status.SCHEDULED, scheduled_at__lte=timezone.now())
        .order_by("scheduled_at", "id")[:limit]
    )
    if not tasks:
        return 0
    from .tasks import run_publish_task

    with publishing_writes():
        for task in tasks:
            task.status = PublishTask.Status.QUEUED
            task.save(update_fields=["status", "updated_at"])
            transaction.on_commit(
                lambda task_id=str(task.id): run_publish_task.delay(task_id)
            )
    return len(tasks)
