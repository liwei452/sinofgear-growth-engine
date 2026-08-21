from celery import shared_task

from apps.ai.orchestration import execute_generation_job
from apps.common.tenant_tasks import (
    TenantWorkResult,
    parse_tenant_organization_id,
    run_tenant_coordinator,
)
from apps.common.tenancy import tenant_atomic
from apps.platforms.lifecycle import refresh_due_credentials
from apps.jobs.services import JobService


@shared_task
def execute_ai_job(organization_id: str, job_id: str, prompt_version_id: str):
    tenant_id = parse_tenant_organization_id(organization_id)
    run = execute_generation_job(
        job_id,
        prompt_version_id=prompt_version_id,
        organization_id=tenant_id,
    )
    return {"ai_run_id": str(run.id), "status": run.status}


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
        with tenant_atomic(organization_id):
            reaped = JobService.reap_stale_jobs(organization_id=organization_id)
        return TenantWorkResult(consumed=reaped, counters={"reaped": reaped})

    return {"reaped": run_tenant_coordinator(reap_one).get("reaped", 0)}
