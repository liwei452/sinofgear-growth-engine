from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import (
    JOB_LEASE_SECONDS,
    JobConflictError,
    JobService,
    StaleJobWorkerError,
)


@pytest.fixture
def organizations(db):
    return (
        Organization.objects.create(name="Jobs Own", slug="jobs-own"),
        Organization.objects.create(name="Jobs Other", slug="jobs-other"),
    )


@pytest.fixture
def job(organizations):
    return JobService.create(
        organization=organizations[0],
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "brief-1", "nested": {"value": 1}},
    )


@pytest.mark.django_db
def test_create_is_idempotent_per_organization_and_input(organizations):
    first = JobService.create(
        organization=organizations[0],
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "same"},
    )
    duplicate = JobService.create(
        organization=organizations[0],
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "same"},
    )
    other_org = JobService.create(
        organization=organizations[1],
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "same"},
    )

    assert duplicate.pk == first.pk
    assert other_org.pk != first.pk


@pytest.mark.django_db
def test_explicit_idempotency_key_rejects_different_input(organizations):
    JobService.create(
        organization=organizations[0],
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "one"},
        idempotency_key="request-1",
    )
    with pytest.raises(JobConflictError):
        JobService.create(
            organization=organizations[0],
            job_type=Job.Type.CONTENT_GENERATE,
            input_snapshot={"brief_id": "two"},
            idempotency_key="request-1",
        )


@pytest.mark.django_db
def test_claim_uses_deterministic_skip_locked_queryset(job):
    with patch.object(
        Job.objects,
        "select_for_update",
        wraps=Job.objects.select_for_update,
    ) as lock:
        claimed = JobService.claim(worker_id="worker-a")

    lock.assert_called_once_with(skip_locked=True)
    assert claimed.pk == job.pk
    assert claimed.status == Job.Status.RUNNING
    assert claimed.claim_token is not None
    assert claimed.claimed_by == "worker-a"
    assert JobService.claim(worker_id="worker-b") is None


@pytest.mark.django_db
def test_progress_is_monotonic_bounded_and_owned(job):
    claimed = JobService.claim(worker_id="worker-a")
    token = claimed.claim_token
    assert JobService.progress(job.id, claim_token=token, progress=25).progress == 25
    with pytest.raises(ValidationError):
        JobService.progress(job.id, claim_token=token, progress=24)
    with pytest.raises(ValidationError):
        JobService.progress(job.id, claim_token=token, progress=101)
    with pytest.raises(StaleJobWorkerError):
        JobService.progress(job.id, claim_token=uuid4(), progress=30)


@pytest.mark.django_db
def test_failed_job_retries_with_exact_original_input_and_new_attempt(job):
    claimed = JobService.claim(worker_id="worker-a")
    original_input = job.input_snapshot
    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error={"code": "provider_error", "message": "safe"},
    )
    retried = JobService.retry(failed.id)

    assert retried.status == Job.Status.RETRY_QUEUED
    assert retried.input_snapshot == original_input
    assert retried.attempt == 2
    assert retried.progress == 0
    assert retried.error is None
    assert retried.result_reference is None
    assert retried.finished_at is None
    assert retried.claim_token is None


@pytest.mark.django_db
def test_stale_worker_cannot_finish_retried_attempt(job):
    first = JobService.claim(worker_id="worker-a")
    old_token = first.claim_token
    JobService.fail(job.id, claim_token=old_token, error={"code": "failed"})
    JobService.retry(job.id)
    second = JobService.claim(worker_id="worker-b")

    with pytest.raises(StaleJobWorkerError):
        JobService.succeed(job.id, claim_token=old_token, result_reference={"id": "old"})
    succeeded = JobService.succeed(
        job.id, claim_token=second.claim_token, result_reference={"id": "new"}
    )
    assert succeeded.status == Job.Status.SUCCEEDED
    assert succeeded.progress == 100
    assert succeeded.error is None


@pytest.mark.django_db
def test_worker_error_and_result_references_are_secret_scrubbed(job):
    claimed = JobService.claim(worker_id="worker-a")
    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error={"code": "provider", "api-key": "hidden", "details": {"token": "x"}},
    )
    assert failed.error == {
        "code": "job_error",
        "message": "Job execution failed.",
    }
    retried = JobService.retry(job.id)
    claimed = JobService.claim(worker_id="worker-b")
    succeeded = JobService.succeed(
        retried.id,
        claim_token=claimed.claim_token,
        result_reference={"ai_run_id": "safe", "Authorization": "hidden"},
    )
    assert succeeded.result_reference == {"ai_run_id": "safe"}


@pytest.mark.django_db
def test_unstructured_worker_error_never_persists_raw_exception_text(job):
    claimed = JobService.claim(worker_id="worker-a")
    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error="Authorization: Bearer top-secret-value",
    )

    assert failed.error == {
        "code": "job_error",
        "message": "Job execution failed.",
    }
    assert "top-secret-value" not in str(failed.error)


@pytest.mark.django_db
def test_structured_worker_error_message_never_persists_secret_text(job):
    claimed = JobService.claim(worker_id="worker-a")
    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error={"code": "provider_error", "message": "api_key=top-secret-value"},
    )

    assert failed.error == {
        "code": "provider_error",
        "message": "AI provider generation failed.",
    }
    assert "top-secret-value" not in str(failed.error)


@pytest.mark.django_db
def test_structured_worker_error_persists_only_controlled_allowlisted_fields(job):
    claimed = JobService.claim(worker_id="worker-a")
    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error={
            "code": "provider_error",
            "message": "attacker-controlled safe-looking text",
            "metadata": {
                "headers": {"x-request-id": "safe", "authorization": "Bearer hidden"},
                "provider_body": "raw upstream response with private details",
                "trace": ["frame one", "frame two"],
            },
            "arbitrary": {"nested": "must not persist"},
        },
    )

    assert failed.error == {
        "code": "provider_error",
        "message": "AI provider generation failed.",
    }
    assert failed.attempts.get(number=1).error == failed.error


@pytest.mark.django_db
@pytest.mark.parametrize("malformed_code", [["provider_error"], {"nested": "value"}, 7])
def test_malformed_structured_error_code_falls_back_safely(job, malformed_code):
    claimed = JobService.claim(worker_id="worker-a")

    failed = JobService.fail(
        job.id,
        claim_token=claimed.claim_token,
        error={"code": malformed_code, "message": "untrusted"},
    )

    assert failed.error == {
        "code": "job_error",
        "message": "Job execution failed.",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("initial", ["QUEUED", "RUNNING", "RETRY_QUEUED"])
def test_cancel_prevents_later_success(job, initial):
    token = None
    if initial == "RUNNING":
        token = JobService.claim(worker_id="worker-a").claim_token
    elif initial == "RETRY_QUEUED":
        claimed = JobService.claim(worker_id="worker-a")
        JobService.fail(job.id, claim_token=claimed.claim_token, error={"code": "failed"})
        JobService.retry(job.id)

    canceled = JobService.cancel(job.id)
    assert canceled.status == Job.Status.CANCELED
    assert canceled.finished_at is not None
    if token:
        with pytest.raises(StaleJobWorkerError):
            JobService.succeed(job.id, claim_token=token, result_reference={"id": "late"})


@pytest.mark.django_db
def test_invalid_transitions_are_rejected(job):
    with pytest.raises(JobConflictError):
        JobService.retry(job.id)
    claimed = JobService.claim(worker_id="worker")
    JobService.succeed(job.id, claim_token=claimed.claim_token, result_reference={"id": "ok"})
    with pytest.raises(JobConflictError):
        JobService.cancel(job.id)


@pytest.mark.django_db
def test_job_history_rejects_direct_bulk_base_and_delete_writes(job):
    job.type = "OTHER"
    with pytest.raises(ValidationError):
        job.save(update_fields=["type"])
    with pytest.raises(ValidationError):
        Job.objects.filter(pk=job.pk).update(status=Job.Status.SUCCEEDED)
    with pytest.raises(ValidationError):
        Job._base_manager.filter(pk=job.pk).update(input_snapshot={"forged": True})
    with pytest.raises(ValidationError):
        Job.objects.bulk_update([job], ["type"])
    with pytest.raises(ValidationError):
        Job.objects.bulk_create(
            [
                Job(
                    organization=job.organization,
                    type=Job.Type.CONTENT_GENERATE,
                    input_snapshot={"forged": True},
                    idempotency_key="forged",
                )
            ]
        )
    with pytest.raises(ValidationError):
        Job._base_manager.bulk_create(
            [
                Job(
                    organization=job.organization,
                    type=Job.Type.CONTENT_GENERATE,
                    input_snapshot={"forged": True},
                    idempotency_key="base-forged",
                )
            ]
        )
    with pytest.raises(ValidationError):
        Job(
            organization=job.organization,
            type=Job.Type.CONTENT_GENERATE,
            input_snapshot={"forged": True},
            idempotency_key="instance-forged",
        ).save()
    with pytest.raises(ValidationError):
        Job.objects.update_or_create(
            pk=job.pk, defaults={"progress": 100}
        )
    with pytest.raises(ValidationError):
        Job._base_manager.update_or_create(
            pk=uuid4(),
            defaults={
                "organization": job.organization,
                "type": Job.Type.CONTENT_GENERATE,
                "input_snapshot": {"forged": True},
                "idempotency_key": "uoc-forged",
            },
        )
    with pytest.raises(ValidationError):
        job.delete()
    with pytest.raises(ValidationError):
        Job._base_manager.filter(pk=job.pk).delete()


@pytest.mark.django_db
def test_heartbeat_extends_lease_and_reaper_fails_stale_running_job(job):
    claimed = JobService.claim(worker_id="worker-a")
    assert claimed.heartbeat_at is not None
    assert claimed.lease_expires_at is not None

    assert JobService.reap_stale_jobs(now=timezone.now()) == 0

    JobService.heartbeat(claimed.id, claim_token=claimed.claim_token)
    claimed.refresh_from_db()
    assert claimed.heartbeat_at > timezone.now() - timedelta(seconds=10)

    expired = timezone.now() + timedelta(seconds=JOB_LEASE_SECONDS + 1)
    assert JobService.reap_stale_jobs(now=expired) == 1

    claimed.refresh_from_db()
    assert claimed.status == Job.Status.FAILED
    assert claimed.error["code"] == "stale_worker"
    assert claimed.claim_token is None
