import pytest

from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.sources.models import IngestionBatch
from apps.sources.services import IngestionService
from apps.sources.tasks import execute_source_import


def make_batch(*, organization, job, user, key="worker-batch"):
    return IngestionBatch.objects.create(
        organization=organization,
        job=job,
        source_type=IngestionBatch.SourceType.URL,
        input_reference={
            "source_url": "https://e.test/worker",
            "original_text": "Need replacement gear",
        },
        idempotency_key=key,
        created_by=user,
    )


@pytest.mark.django_db
def test_worker_claims_runs_and_succeeds_job(organization, job, user):
    batch = make_batch(organization=organization, job=job, user=user)

    result = execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    batch.refresh_from_db()
    assert result == {"ingestion_batch_id": str(batch.id), "status": "SUCCEEDED"}
    assert job.status == Job.Status.SUCCEEDED
    assert job.result_reference == {"ingestion_batch_id": str(batch.id)}
    assert batch.status == IngestionBatch.Status.SUCCEEDED


@pytest.mark.django_db
def test_worker_failure_marks_owned_job_failed_and_reraises(
    organization, job, user, monkeypatch
):
    batch = make_batch(organization=organization, job=job, user=user, key="worker-failure")

    def fail_run(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(IngestionService, "run", fail_run)

    with pytest.raises(RuntimeError, match="database unavailable"):
        execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert job.error == {
        "code": "SOURCE_IMPORT_FAILED",
        "message": "Public source import failed.",
    }


@pytest.mark.django_db
def test_worker_does_not_mask_original_failure_when_claim_becomes_stale(
    organization, job, user, monkeypatch
):
    batch = make_batch(organization=organization, job=job, user=user, key="worker-stale")

    def cancel_then_fail(**_kwargs):
        JobService.cancel(job.id, organization=organization)
        raise RuntimeError("original ingestion failure")

    monkeypatch.setattr(IngestionService, "run", cancel_then_fail)

    with pytest.raises(RuntimeError, match="original ingestion failure"):
        execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    assert job.status == Job.Status.CANCELED


@pytest.mark.django_db
def test_worker_without_a_claimable_job_leaves_state_unchanged(organization, job, user):
    batch = make_batch(organization=organization, job=job, user=user, key="worker-unchanged")
    claimed = JobService.claim(worker_id="another-worker", job_id=job.id)

    result = execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    batch.refresh_from_db()
    assert result == {"job_id": str(job.id), "status": "UNCHANGED"}
    assert job.status == Job.Status.RUNNING
    assert job.claim_token == claimed.claim_token
    assert batch.status == IngestionBatch.Status.QUEUED
