from celery import shared_task

from apps.ai.orchestration import execute_generation_job
from apps.common.tenant_tasks import (
    TenantWorkResult,
    require_tenant_object,
    run_tenant_coordinator,
    tenant_task_context,
)
from apps.jobs.models import Job
from apps.platforms.lifecycle import refresh_due_credentials
from apps.jobs.services import JobService


@shared_task
def execute_ai_job(organization_id: str, job_id: str, prompt_version_id: str):
    failure = None
    with tenant_task_context(organization_id) as tenant_id:
        try:
            require_tenant_object(Job, tenant_id, pk=job_id)
            run = execute_generation_job(job_id, prompt_version_id=prompt_version_id)
            task_result = {"ai_run_id": str(run.id), "status": run.status}
        except Exception as error:
            failure = error
    if failure is not None:
        raise failure
    return task_result


@shared_task
def refresh_social_credentials():
    def refresh_one(organization_id, remaining):
        counters = refresh_due_credentials(
            organization_id=organization_id,
            limit=remaining,
        )
        return TenantWorkResult(consumed=counters["examined"], counters=counters)

    result = run_tenant_coordinator(refresh_one, limit=100)
    return {
        key: result.get(key, 0)
        for key in ("examined", "refreshed", "reauthorization_required", "failed")
    }


@shared_task
def reap_stale_jobs():
    def reap_one(organization_id, _remaining):
        reaped = JobService.reap_stale_jobs(organization_id=organization_id)
        return TenantWorkResult(consumed=reaped, counters={"reaped": reaped})

    return {"reaped": run_tenant_coordinator(reap_one).get("reaped", 0)}
