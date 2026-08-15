from celery import shared_task
from django.conf import settings

from apps.ai.orchestration import execute_generation_job
from apps.ai.models import AIRun

from .models import ContentRecommendation
from .recommendations import finalize_recommendation_result
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


@shared_task
def generate_content_recommendations_job(job_id, prompt_version_id):
    recommendation = ContentRecommendation.objects.get(job_id=job_id)
    if recommendation.status == ContentRecommendation.Status.QUEUED:
        recommendation.status = ContentRecommendation.Status.RUNNING
        recommendation.save(update_fields=["status", "updated_at"])
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        provider_code=settings.PRODUCT_AI_PROVIDER,
        provider_model=settings.PRODUCT_AI_MODEL,
        result_writer=finalize_recommendation_result,
    )
    if run.status in {AIRun.Status.FAILED, AIRun.Status.CANCELED}:
        recommendation.refresh_from_db()
        if recommendation.status != ContentRecommendation.Status.ARCHIVED:
            recommendation.status = ContentRecommendation.Status.FAILED
            recommendation.save(update_fields=["status", "updated_at"])
    return {"ai_run_id": str(run.id), "status": run.status}
