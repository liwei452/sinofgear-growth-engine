from celery import shared_task

from apps.ai.orchestration import ProviderRetryRequired

from .orchestration import execute_lead_analysis_job


@shared_task(bind=True, max_retries=2)
def execute_lead_analysis(self, job_id: str, prompt_version_id: str | None = None):
    try:
        run = execute_lead_analysis_job(job_id, prompt_version_id)
    except ProviderRetryRequired as retry:
        raise self.retry(countdown=retry.countdown) from None
    result = dict(run.job.result_reference or {})
    result["status"] = run.status
    return result
