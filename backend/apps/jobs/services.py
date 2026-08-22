import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.security import normalize_persisted_error, scrub_secrets

from .models import Job, JobAttempt, job_service_writes


JOB_LEASE_SECONDS = 300


class JobConflictError(ValueError):
    pass


class StaleJobWorkerError(JobConflictError):
    pass


TERMINAL_STATUSES = frozenset(
    {Job.Status.SUCCEEDED, Job.Status.FAILED, Job.Status.CANCELED}
)
TRANSITIONS = {
    Job.Status.QUEUED: frozenset({Job.Status.RUNNING, Job.Status.CANCELED}),
    Job.Status.RETRY_QUEUED: frozenset({Job.Status.RUNNING, Job.Status.CANCELED}),
    Job.Status.RUNNING: frozenset(
        {Job.Status.SUCCEEDED, Job.Status.FAILED, Job.Status.CANCELED}
    ),
    Job.Status.FAILED: frozenset({Job.Status.RETRY_QUEUED}),
    Job.Status.SUCCEEDED: frozenset(),
    Job.Status.CANCELED: frozenset(),
}


def _json_copy(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Job input must be JSON serializable.") from exc
    return json.loads(encoded)


def _input_digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalized_error(error) -> dict[str, object]:
    return normalize_persisted_error(error)


class JobService:
    @staticmethod
    @transaction.atomic
    def create(
        *,
        organization,
        job_type: str,
        input_snapshot,
        idempotency_key: str | None = None,
        created_by=None,
        max_attempts: int = 3,
    ) -> Job:
        if job_type not in Job.Type.values:
            raise ValidationError("Unsupported job type.")
        if max_attempts < 1:
            raise ValidationError("max_attempts must be positive.")
        frozen = _json_copy(scrub_secrets(input_snapshot))
        key = idempotency_key.strip() if idempotency_key else _input_digest(frozen)
        if not key:
            raise ValidationError("idempotency_key must not be blank.")
        existing = Job.objects.filter(
            organization=organization, type=job_type, idempotency_key=key
        ).first()
        if existing:
            if existing.input_snapshot != frozen:
                raise JobConflictError("Idempotency key already has different input.")
            return existing
        try:
            with transaction.atomic(), job_service_writes():
                return Job.objects.create(
                    organization=organization, type=job_type,
                    input_snapshot=frozen, idempotency_key=key,
                    created_by=created_by, max_attempts=max_attempts,
                )
        except IntegrityError:
            existing = Job.objects.get(
                organization=organization, type=job_type, idempotency_key=key
            )
            if existing.input_snapshot != frozen:
                raise JobConflictError("Idempotency key already has different input.")
            return existing

    @staticmethod
    @transaction.atomic
    def claim(
        *, worker_id: str, organization=None, job_type: str | None = None, job_id=None
    ):
        queryset = Job.objects.select_for_update(skip_locked=True).filter(
            status__in=[Job.Status.QUEUED, Job.Status.RETRY_QUEUED]
        )
        if organization is not None:
            queryset = queryset.filter(organization=organization)
        if job_type is not None:
            queryset = queryset.filter(type=job_type)
        if job_id is not None:
            queryset = queryset.filter(pk=job_id)
        job = queryset.order_by("created_at", "id").first()
        if job is None:
            return None
        now = timezone.now()
        token = uuid4()
        job.status = Job.Status.RUNNING
        job.claim_token = token
        job.claimed_by = worker_id
        job.claimed_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=JOB_LEASE_SECONDS)
        job.started_at = job.started_at or now
        job.finished_at = None
        job.version += 1
        with job_service_writes():
            job.save(
                update_fields=[
                    "status", "claim_token", "claimed_by", "claimed_at",
                    "heartbeat_at", "lease_expires_at",
                    "started_at", "finished_at", "version", "updated_at",
                ]
            )
            JobAttempt.objects.create(
                job=job,
                number=job.attempt,
                claim_token=token,
                worker_id=worker_id,
                status=JobAttempt.Status.RUNNING,
                started_at=now,
            )
        return job

    @staticmethod
    @transaction.atomic
    def progress(job_id: UUID, *, claim_token: UUID, progress: int) -> Job:
        job = JobService._locked(job_id)
        JobService._require_owner(job, claim_token)
        if not isinstance(progress, int) or isinstance(progress, bool) or not 0 <= progress <= 100:
            raise ValidationError("Progress must be an integer from 0 to 100.")
        if progress < job.progress:
            raise ValidationError("Progress cannot decrease within an attempt.")
        job.progress = progress
        job.version += 1
        JobService._save(job, ["progress", "version", "updated_at"])
        return job

    @staticmethod
    @transaction.atomic
    def heartbeat(job_id: UUID, *, claim_token: UUID) -> Job:
        job = JobService._locked(job_id)
        JobService._require_owner(job, claim_token)
        now = timezone.now()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=JOB_LEASE_SECONDS)
        job.version += 1
        JobService._save(job, ["heartbeat_at", "lease_expires_at", "version", "updated_at"])
        return job

    @staticmethod
    @transaction.atomic
    def reap_stale_jobs(*, organization_id, now=None) -> int:
        now = now or timezone.now()
        stale = list(
            Job.objects.select_for_update(skip_locked=True)
            .filter(
                organization_id=organization_id,
                status=Job.Status.RUNNING,
                lease_expires_at__lt=now,
            )
        )
        for job in stale:
            token = job.claim_token
            error = normalize_persisted_error({
                "code": "stale_worker",
                "message": "Worker lease expired without heartbeat.",
            })
            job.status = Job.Status.FAILED
            job.error = error
            job.result_reference = None
            job.finished_at = now
            job.claim_token = None
            job.version += 1
            JobService._save(
                job,
                ["status", "error", "result_reference", "finished_at",
                 "claim_token", "version", "updated_at"],
            )
            if token:
                JobService._finish_attempt(token, JobAttempt.Status.FAILED, now, error=error)
        return len(stale)

    @staticmethod
    @transaction.atomic
    def succeed(job_id: UUID, *, claim_token: UUID, result_reference) -> Job:
        job = JobService._locked(job_id)
        JobService._require_owner(job, claim_token)
        result = _json_copy(scrub_secrets(result_reference))
        now = timezone.now()
        job.status = Job.Status.SUCCEEDED
        job.progress = 100
        job.result_reference = result
        job.error = None
        job.finished_at = now
        job.claim_token = None
        job.version += 1
        JobService._save(job, ["status", "progress", "result_reference", "error", "finished_at", "claim_token", "version", "updated_at"])
        JobService._finish_attempt(claim_token, JobAttempt.Status.SUCCEEDED, now, result_reference=result)
        return job

    @staticmethod
    @transaction.atomic
    def fail(job_id: UUID, *, claim_token: UUID, error) -> Job:
        job = JobService._locked(job_id)
        JobService._require_owner(job, claim_token)
        normalized = _normalized_error(error)
        now = timezone.now()
        job.status = Job.Status.FAILED
        job.error = normalized
        job.result_reference = None
        job.finished_at = now
        job.claim_token = None
        job.version += 1
        JobService._save(job, ["status", "error", "result_reference", "finished_at", "claim_token", "version", "updated_at"])
        JobService._finish_attempt(claim_token, JobAttempt.Status.FAILED, now, error=normalized)
        return job

    @staticmethod
    @transaction.atomic
    def retry(job_id: UUID, *, organization=None) -> Job:
        job = JobService._locked(job_id, organization=organization)
        if job.status != Job.Status.FAILED:
            raise JobConflictError("Only failed jobs can be retried.")
        if job.attempt >= job.max_attempts:
            raise JobConflictError("Job retry limit reached.")
        job.status = Job.Status.RETRY_QUEUED
        job.progress = 0
        job.attempt += 1
        job.claim_token = None
        job.claimed_by = ""
        job.claimed_at = None
        job.finished_at = None
        job.error = None
        job.result_reference = None
        job.version += 1
        JobService._save(job, ["status", "progress", "attempt", "claim_token", "claimed_by", "claimed_at", "finished_at", "error", "result_reference", "version", "updated_at"])
        return job

    @staticmethod
    @transaction.atomic
    def cancel(job_id: UUID, *, organization=None) -> Job:
        job = JobService._locked(job_id, organization=organization)
        if Job.Status.CANCELED not in TRANSITIONS[job.status]:
            raise JobConflictError(f"Cannot cancel job in status {job.status}.")
        token = job.claim_token
        now = timezone.now()
        job.status = Job.Status.CANCELED
        job.finished_at = now
        job.result_reference = None
        job.claim_token = None
        job.version += 1
        JobService._save(job, ["status", "finished_at", "result_reference", "claim_token", "version", "updated_at"])
        if token:
            JobService._finish_attempt(token, JobAttempt.Status.CANCELED, now)
        return job

    @staticmethod
    def _locked(job_id, *, organization=None) -> Job:
        queryset = Job.objects.select_for_update()
        if organization is not None:
            queryset = queryset.filter(organization=organization)
        return queryset.get(pk=job_id)

    @staticmethod
    def _require_owner(job: Job, claim_token: UUID) -> None:
        if job.status != Job.Status.RUNNING or job.claim_token != claim_token:
            raise StaleJobWorkerError("Worker no longer owns this job attempt.")

    @staticmethod
    def _save(job: Job, fields: list[str]) -> None:
        with job_service_writes():
            job.save(update_fields=fields)

    @staticmethod
    def _finish_attempt(token, status, finished_at, **values) -> None:
        attempt = JobAttempt.objects.select_for_update().get(claim_token=token)
        attempt.status = status
        attempt.finished_at = finished_at
        for field, value in values.items():
            setattr(attempt, field, deepcopy(value))
        with job_service_writes():
            attempt.save(update_fields=["status", "finished_at", *values])
