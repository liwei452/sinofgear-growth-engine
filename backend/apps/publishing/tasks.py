from celery import shared_task

from apps.common.tenant_tasks import (
    TenantWorkResult,
    require_tenant_object,
    run_tenant_coordinator,
    tenant_task_context,
)

from .models import PublishTask
from .services import (
    enqueue_due_publish_tasks,
    execute_publish_task,
    reap_stale_publish_tasks,
)
from .metrics import sync_post_metrics
from .reconciliation import (
    BUFFER_RECONCILIATION_BATCH_SIZE,
    reconcile_publish_task,
    select_due_buffer_reconciliation_ids,
)


@shared_task
def run_publish_task(organization_id, task_id):
    from apps.growth.tasks import sync_growth_publish_item_from_task

    failure = None
    with tenant_task_context(organization_id) as tenant_id:
        require_tenant_object(PublishTask, tenant_id, pk=task_id)
        try:
            post = execute_publish_task(task_id)
        except Exception as error:
            failure = error
            post = None
        task_result = {
            "task_id": str(task_id),
            "published_post_id": str(post.id) if post else None,
        }
    sync_growth_publish_item_from_task.delay(organization_id, str(task_id))
    if failure is not None:
        raise failure
    return task_result


@shared_task
def queue_due_publish_tasks(limit=100):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Queue limit must be an integer from 1 to 500.")

    def enqueue_one(organization_id, remaining):
        queued = enqueue_due_publish_tasks(
            organization_id=organization_id,
            limit=remaining,
        )
        return TenantWorkResult(consumed=queued, counters={"queued": queued})

    return {"queued": run_tenant_coordinator(enqueue_one, limit=limit).get("queued", 0)}


@shared_task
def sync_post_metrics_hourly():
    from apps.identity.models import Organization

    def sync_one(organization_id, _remaining):
        synced = sync_post_metrics(
            organization=Organization.objects.get(pk=organization_id)
        )
        return TenantWorkResult(consumed=synced, counters={"synced": synced})

    return {"synced": run_tenant_coordinator(sync_one).get("synced", 0)}


@shared_task
def reap_stale_publish_tasks_task():
    def reap_one(organization_id, _remaining):
        reaped = reap_stale_publish_tasks(organization_id=organization_id)
        return TenantWorkResult(consumed=reaped, counters={"reaped": reaped})

    return {"reaped": run_tenant_coordinator(reap_one).get("reaped", 0)}


@shared_task
def reconcile_buffer_publish_task_job(organization_id, task_id):
    from apps.identity.models import Organization

    with tenant_task_context(organization_id) as tenant_id:
        require_tenant_object(PublishTask, tenant_id, pk=task_id)
        task = reconcile_publish_task(
            task_id,
            organization=Organization.objects.get(pk=tenant_id),
        )
        return {"task_id": str(task.id), "status": task.status}


@shared_task
def reconcile_buffer_publish_tasks(limit=50):
    if type(limit) is not int:
        raise ValueError("Reconciliation limit must be an integer.")
    limit = min(max(limit, 1), BUFFER_RECONCILIATION_BATCH_SIZE)
    dispatches = []

    def reconcile_one(organization_id, remaining):
        task_ids = select_due_buffer_reconciliation_ids(
            organization_id=organization_id,
            limit=remaining,
        )
        for task_id in task_ids:
            dispatches.append((str(organization_id), str(task_id)))
        queued = len(task_ids)
        return TenantWorkResult(consumed=queued, counters={"queued": queued})

    queued = run_tenant_coordinator(reconcile_one, limit=limit).get("queued", 0)
    for organization_id, task_id in dispatches:
        reconcile_buffer_publish_task_job.delay(organization_id, task_id)
    return {"queued": queued}
