from celery import shared_task

from .orchestration import execute_lead_analysis_job


@shared_task
def execute_lead_analysis(job_id: str, prompt_version_id: str | None = None):
    run = execute_lead_analysis_job(job_id, prompt_version_id)
    result = dict(run.job.result_reference or {})
    result["status"] = run.status
    return result
