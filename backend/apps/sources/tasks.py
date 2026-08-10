from celery import shared_task

from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError

from .services import IngestionService


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
