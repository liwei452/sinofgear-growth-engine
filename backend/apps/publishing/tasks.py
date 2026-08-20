from celery import shared_task

from .services import (
    enqueue_due_publish_tasks,
    execute_publish_task,
    reap_stale_publish_tasks,
)
from .metrics import sync_post_metrics
from .reconciliation import (
    reconcile_publish_task,
    select_due_buffer_reconciliation_ids,
)


@shared_task
def run_publish_task(task_id):
    from apps.growth.tasks import sync_growth_publish_item_from_task

    post = None
    try:
        post = execute_publish_task(task_id)
    finally:
        sync_growth_publish_item_from_task.delay(str(task_id))
    return {
        "task_id": str(task_id),
        "published_post_id": str(post.id) if post else None,
    }


@shared_task
def queue_due_publish_tasks(limit=100):
    return {"queued": enqueue_due_publish_tasks(limit=limit)}


@shared_task
def sync_post_metrics_hourly():
    from apps.identity.models import Organization

    synced = 0
    for organization in Organization.objects.all():
        synced += sync_post_metrics(organization=organization)
    return {"synced": synced}


@shared_task
def reap_stale_publish_tasks_task():
    return {"reaped": reap_stale_publish_tasks()}


@shared_task
def reconcile_buffer_publish_task_job(task_id):
    task = reconcile_publish_task(task_id)
    return {"task_id": str(task.id), "status": task.status}


@shared_task
def reconcile_buffer_publish_tasks(limit=50):
    task_ids = select_due_buffer_reconciliation_ids(limit=limit)
    for task_id in task_ids:
        reconcile_buffer_publish_task_job.delay(str(task_id))
    return {"queued": len(task_ids)}
