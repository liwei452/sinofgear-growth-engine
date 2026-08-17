from celery import shared_task

from .understanding import execute_understanding_job


@shared_task
def run_asset_understanding(job_id: str):
    result = execute_understanding_job(job_id)
    return {"job_id": str(result.job.id), "status": result.job.status}
