from celery import shared_task

from apps.common.tenant_tasks import require_tenant_object, tenant_task_context
from apps.jobs.models import Job

from .understanding import execute_understanding_job


@shared_task
def run_asset_understanding(organization_id: str, job_id: str):
    failure = None
    with tenant_task_context(organization_id) as tenant_id:
        try:
            require_tenant_object(Job, tenant_id, pk=job_id)
            result = execute_understanding_job(job_id)
            task_result = {"job_id": str(result.job.id), "status": result.job.status}
        except Exception as error:
            failure = error
    if failure is not None:
        raise failure
    return task_result
