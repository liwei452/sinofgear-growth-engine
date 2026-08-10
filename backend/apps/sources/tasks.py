from datetime import datetime

from celery import shared_task
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError

from .services import (
    IngestionService,
    RETENTION_POLICY_VERSION,
    RetentionService,
    retention_cleanup_job_snapshot,
)


@shared_task
def execute_source_import(job_id: str, batch_id: str):
    job = JobService.claim(
        worker_id="source-import-worker",
        job_id=job_id,
        job_type=Job.Type.SOURCE_IMPORT,
    )
    if job is None:
        return {"job_id": job_id, "status": "UNCHANGED"}
    claim_token = job.claim_token
    try:
        batch = IngestionService.run(
            batch_id=batch_id,
            organization=job.organization,
            claim_token=claim_token,
        )
        if IngestionService.preflight_failed(batch):
            JobService.fail(
                job.id,
                claim_token=claim_token,
                error={
                    "code": "SOURCE_IMPORT_FAILED",
                    "message": "Public source import failed.",
                },
            )
        else:
            JobService.succeed(
                job.id,
                claim_token=claim_token,
                result_reference={"ingestion_batch_id": str(batch.id)},
            )
    except Exception:
        try:
            JobService.fail(
                job.id,
                claim_token=claim_token,
                error={
                    "code": "SOURCE_IMPORT_FAILED",
                    "message": "Public source import failed.",
                },
            )
        except StaleJobWorkerError:
            pass
        raise
    return {"ingestion_batch_id": str(batch.id), "status": batch.status}


@shared_task
def execute_retention_cleanup(job_id: str):
    job = JobService.claim(
        worker_id="source-retention-worker",
        job_id=job_id,
        job_type=Job.Type.RETENTION_CLEANUP,
    )
    if job is None:
        return {"job_id": job_id, "status": "UNCHANGED"}
    claim_token = job.claim_token
    try:
        snapshot = job.input_snapshot
        if not isinstance(snapshot, dict):
            raise ValidationError("Retention job input is invalid.")
        try:
            cutoff = datetime.fromisoformat(snapshot.get("cutoff", ""))
        except (TypeError, ValueError) as error:
            raise ValidationError("Retention job cutoff is invalid.") from error
        expected = retention_cleanup_job_snapshot(
            organization=job.organization,
            cutoff=cutoff,
        )
        if snapshot != expected:
            raise ValidationError("Retention job identity does not match its organization or policy.")
        with transaction.atomic():
            result = RetentionService.cleanup_owned(
                organization=job.organization,
                cutoff=cutoff,
                actor=job.created_by,
                job_id=job.id,
                claim_token=claim_token,
            )
            result_reference = {
                "policy_version": RETENTION_POLICY_VERSION,
                **result.as_dict(),
            }
            JobService.succeed(
                job.id,
                claim_token=claim_token,
                result_reference=result_reference,
            )
    except Exception:
        try:
            JobService.fail(
                job.id,
                claim_token=claim_token,
                error={
                    "code": "RETENTION_CLEANUP_FAILED",
                    "message": "Source evidence retention cleanup failed.",
                },
            )
        except StaleJobWorkerError:
            pass
        raise
    return {"job_id": str(job.id), "status": "SUCCEEDED", **result_reference}
