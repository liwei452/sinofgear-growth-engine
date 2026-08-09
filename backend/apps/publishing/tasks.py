from celery import shared_task

from .services import enqueue_due_publish_tasks, execute_publish_task


@shared_task
def run_publish_task(task_id):
    post = execute_publish_task(task_id)
    return {
        "task_id": str(task_id),
        "published_post_id": str(post.id) if post else None,
    }


@shared_task
def queue_due_publish_tasks(limit=100):
    return {"queued": enqueue_due_publish_tasks(limit=limit)}
