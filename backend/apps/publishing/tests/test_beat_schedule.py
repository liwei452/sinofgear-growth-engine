from django.conf import settings


def test_scheduled_publish_sweep_is_registered_in_celery_beat():
    schedule = settings.CELERY_BEAT_SCHEDULE

    entry = schedule.get("publishing-queue-due-minute")

    assert entry is not None
    assert entry["task"] == "apps.publishing.tasks.queue_due_publish_tasks"
    assert entry["schedule"] > 0
