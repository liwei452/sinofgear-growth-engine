from django.db.models import Count

from apps.publishing.models import LIVE_PUBLISH_TASK_STATUSES, PublishTask


GROUP_FIELDS = (
    "organization_id",
    "platform_content_id",
    "content_version",
    "social_account_id",
)


def find_duplicate_live_publish_task_groups():
    """Return task IDs and statuses only; this audit deliberately performs no writes."""
    live_tasks = PublishTask.objects.filter(status__in=LIVE_PUBLISH_TASK_STATUSES)
    duplicate_keys = (
        live_tasks.values(*GROUP_FIELDS)
        .annotate(task_count=Count("id"))
        .filter(task_count__gt=1)
        .order_by(*GROUP_FIELDS)
    )
    groups = []
    for key in duplicate_keys:
        filters = {field: key[field] for field in GROUP_FIELDS}
        groups.append(
            list(
                live_tasks.filter(**filters)
                .order_by("id")
                .values("id", "status")
            )
        )
    return groups
