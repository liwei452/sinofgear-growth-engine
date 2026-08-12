from celery import shared_task

from apps.ai.orchestration import ProviderRetryRequired, execute_generation_job

from .services import finalize_master_result


@shared_task(bind=True, max_retries=2)
def generate_master_content_job(self, job_id, prompt_version_id):
    try:
        run = execute_generation_job(
            job_id,
            prompt_version_id=prompt_version_id,
            result_writer=finalize_master_result,
        )
    except ProviderRetryRequired as retry:
        raise self.retry(countdown=retry.countdown) from None
    return {"ai_run_id": str(run.id), "status": run.status}
