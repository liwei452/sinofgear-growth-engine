from django.conf import settings


def test_scheduled_publish_sweep_is_registered_in_celery_beat():
    schedule = settings.CELERY_BEAT_SCHEDULE

    entry = schedule.get("publishing-queue-due-minute")

    assert entry is not None
    assert entry["task"] == "apps.publishing.tasks.queue_due_publish_tasks"
    assert entry["schedule"] > 0


def test_buffer_reconciliation_sweep_is_registered_every_minute():
    entry = settings.CELERY_BEAT_SCHEDULE.get("publishing-buffer-reconciliation-minute")

    assert entry == {
        "task": "apps.publishing.tasks.reconcile_buffer_publish_tasks",
        "schedule": 60.0,
    }
