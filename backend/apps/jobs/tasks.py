from celery import shared_task

from apps.ai.orchestration import execute_generation_job
from apps.platforms.lifecycle import refresh_due_credentials


@shared_task
def execute_ai_job(job_id: str, prompt_version_id: str):
    run = execute_generation_job(job_id, prompt_version_id=prompt_version_id)
    return {"ai_run_id": str(run.id), "status": run.status}


@shared_task
def refresh_social_credentials(organization_id: str | None = None):
    return refresh_due_credentials(organization_id=organization_id, limit=100)
