from celery import shared_task

from django.contrib.auth import get_user_model

from apps.ai.orchestration import execute_generation_job
from apps.ai.models import AIRun
from apps.jobs.models import Job

from .models import ContentRecommendation, MasterContent
from .recommendations import finalize_recommendation_result
from .services import finalize_master_result, finalize_platform_variants


@shared_task
def generate_master_content_job(job_id, prompt_version_id):
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        result_writer=finalize_master_result,
    )
    if run.status == AIRun.Status.SUCCEEDED:
        job = Job.objects.get(pk=job_id)
        reference = job.result_reference or {}
        master_id = reference.get("id")
        if master_id:
            master = MasterContent.objects.filter(
                id=master_id, organization=job.organization
            ).first()
            if master is not None:
                actor = job.created_by
                if actor is None:
                    actor, _ = get_user_model().objects.get_or_create(
                        username="system-auto-approve"
                    )
                finalize_platform_variants(master, actor)
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
        result_writer=finalize_recommendation_result,
    )
    if run.status in {AIRun.Status.FAILED, AIRun.Status.CANCELED}:
        recommendation.refresh_from_db()
        if recommendation.status != ContentRecommendation.Status.ARCHIVED:
            recommendation.status = ContentRecommendation.Status.FAILED
            recommendation.save(update_fields=["status", "updated_at"])
    return {"ai_run_id": str(run.id), "status": run.status}
