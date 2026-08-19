from celery import shared_task

from django.contrib.auth import get_user_model

from apps.ai.orchestration import execute_generation_job
from apps.ai.models import AIRun
from apps.jobs.models import Job
from apps.jobs.services import JobService

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
            actor = job.created_by
            if actor is None:
                actor, _ = get_user_model().objects.get_or_create(
                    username="system-auto-approve"
                )
            child = JobService.create(
                organization=job.organization,
                job_type=Job.Type.CONTENT_PLATFORM_VARIANTS,
                input_snapshot={"master_id": master_id, "actor_id": actor.id},
                idempotency_key=f"platform-variants:{master_id}",
                created_by=actor,
            )
            generate_platform_variants_job.delay(child.id)
    return {"ai_run_id": str(run.id), "status": run.status}


@shared_task
def generate_platform_variants_job(job_id):
    job = Job.objects.get(pk=job_id)
    claimed = JobService.claim(worker_id="platform-variants-worker", job_id=job_id)
    if claimed is None:
        job.refresh_from_db()
        return {"job_id": str(job.id), "status": job.status}
    try:
        snapshot = claimed.input_snapshot or {}
        master = MasterContent.objects.get(
            id=snapshot["master_id"], organization=claimed.organization
        )
        actor_id = snapshot.get("actor_id")
        actor = get_user_model().objects.filter(id=actor_id).first()
        if actor is None:
            actor, _ = get_user_model().objects.get_or_create(
                username="system-auto-approve"
            )
        created = finalize_platform_variants(master, actor)
        result_reference = {
            "type": "platform_variants",
            "platform_content_ids": [str(content.id) for content in created],
        }
        JobService.succeed(
            job_id,
            claim_token=claimed.claim_token,
            result_reference=result_reference,
        )
        return {
            "job_id": str(job.id),
            "status": Job.Status.SUCCEEDED,
            "platform_content_ids": [str(content.id) for content in created],
        }
    except Exception as error:
        JobService.fail(
            job_id,
            claim_token=claimed.claim_token,
            error={"code": "PLATFORM_VARIANTS_FAILED", "message": str(error)},
        )
        raise


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
