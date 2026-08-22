from celery import shared_task

from django.contrib.auth import get_user_model

from apps.ai.orchestration import execute_generation_job
from apps.ai.models import AIRun
from apps.common.tenant_tasks import (
    parse_tenant_organization_id,
    require_tenant_object,
    tenant_task_context,
)
from apps.common.tenancy import tenant_atomic
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.knowledge.agent_context import AgentContextPurpose, load_agent_context

from .models import ContentRecommendation, MasterContent
from .recommendations import finalize_recommendation_result
from .services import finalize_master_result, finalize_platform_variants


def _platform_variant_job_input(master: MasterContent, actor) -> dict:
    payload = {"master_id": str(master.id), "actor_id": actor.id}
    if master.knowledge_context_snapshot_id is None:
        return payload
    snapshot = master.knowledge_context_snapshot
    context = load_agent_context(
        organization=master.organization,
        mission=snapshot.mission,
        snapshot_id=snapshot.id,
    )
    provenance = dict(context.provenance)
    if master.provenance.get("knowledge_context") != provenance:
        raise ValueError("Master knowledge context provenance is inconsistent.")
    payload.update(
        {
            "knowledge_provenance": provenance,
            "agent_context": context.for_purpose(
                AgentContextPurpose.PLATFORM_VARIANT
            ).to_dict(),
        }
    )
    return payload


@shared_task
def generate_master_content_job(organization_id, job_id, prompt_version_id):
    child_dispatch = None
    tenant_id = parse_tenant_organization_id(organization_id)
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        result_writer=finalize_master_result,
        organization_id=tenant_id,
    )
    with tenant_atomic(tenant_id):
        job = Job.objects.get(pk=job_id, organization_id=tenant_id)
        if run.status != AIRun.Status.SUCCEEDED:
            task_result = {"ai_run_id": str(run.id), "status": run.status}
        else:
            job.refresh_from_db()
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
                    input_snapshot=_platform_variant_job_input(
                        MasterContent.objects.select_related(
                            "organization",
                            "knowledge_context_snapshot__mission",
                        ).get(pk=master_id, organization=job.organization),
                        actor,
                    ),
                    idempotency_key=f"platform-variants:{master_id}",
                    created_by=actor,
                )
                child_dispatch = (str(tenant_id), str(child.id))
            task_result = {"ai_run_id": str(run.id), "status": run.status}
    if child_dispatch is not None:
        generate_platform_variants_job.delay(
            child_dispatch[0],
            child_dispatch[1],
        )
    return task_result


@shared_task
def generate_platform_variants_job(organization_id, job_id):
    failure = None
    with tenant_task_context(organization_id) as tenant_id:
        job = require_tenant_object(Job, tenant_id, pk=job_id)
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
            expected = _platform_variant_job_input(master, actor)
            if any(
                snapshot.get(key) != expected.get(key)
                for key in (
                    "master_id",
                    "knowledge_provenance",
                    "agent_context",
                )
            ):
                raise ValueError("Platform Job knowledge context is inconsistent.")
            created = finalize_platform_variants(master, actor)
            result_reference = {
                "type": "platform_variants",
                "platform_content_ids": [str(content.id) for content in created],
            }
            if expected.get("knowledge_provenance") is not None:
                result_reference["knowledge_provenance"] = expected[
                    "knowledge_provenance"
                ]
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
            failure = error
    if failure is not None:
        raise failure


@shared_task
def generate_content_recommendations_job(organization_id, job_id, prompt_version_id):
    tenant_id = parse_tenant_organization_id(organization_id)
    with tenant_atomic(tenant_id):
        recommendation = ContentRecommendation.objects.get(
            organization_id=tenant_id, job_id=job_id
        )
        if recommendation.status == ContentRecommendation.Status.QUEUED:
            recommendation.status = ContentRecommendation.Status.RUNNING
            recommendation.save(update_fields=["status", "updated_at"])
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        result_writer=finalize_recommendation_result,
        organization_id=tenant_id,
    )
    with tenant_atomic(tenant_id):
        if run is not None and run.status in {
            AIRun.Status.FAILED,
            AIRun.Status.CANCELED,
        }:
            recommendation.refresh_from_db()
            if recommendation.status != ContentRecommendation.Status.ARCHIVED:
                recommendation.status = ContentRecommendation.Status.FAILED
                recommendation.save(update_fields=["status", "updated_at"])
        task_result = (
            {"ai_run_id": str(run.id), "status": run.status}
            if run is not None
            else None
        )
    return task_result
