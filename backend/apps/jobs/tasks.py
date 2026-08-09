from celery import shared_task

from apps.ai.orchestration import execute_generation_job


@shared_task
def execute_ai_job(job_id: str, prompt_version_id: str):
    run = execute_generation_job(job_id, prompt_version_id=prompt_version_id)
    return {"ai_run_id": str(run.id), "status": run.status}
