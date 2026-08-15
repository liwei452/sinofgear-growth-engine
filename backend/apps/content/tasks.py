from celery import shared_task
from django.conf import settings

from apps.ai.orchestration import execute_generation_job

from .services import finalize_master_result


@shared_task
def generate_master_content_job(job_id, prompt_version_id):
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        provider_code=settings.PRODUCT_AI_PROVIDER,
        provider_model=settings.PRODUCT_AI_MODEL,
        result_writer=finalize_master_result,
    )
    return {"ai_run_id": str(run.id), "status": run.status}
