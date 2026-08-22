from celery import shared_task

from apps.common.tenant_tasks import parse_tenant_organization_id

from .understanding import execute_understanding_job


@shared_task
def run_asset_understanding(organization_id: str, job_id: str):
    tenant_id = parse_tenant_organization_id(organization_id)
    result = execute_understanding_job(job_id, organization_id=tenant_id)
    return {"job_id": str(result.job.id), "status": result.job.status}
