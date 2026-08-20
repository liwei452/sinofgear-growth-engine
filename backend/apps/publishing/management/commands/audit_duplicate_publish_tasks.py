from django.core.management.base import BaseCommand, CommandError

from apps.publishing.duplicate_live_tasks import find_duplicate_live_publish_task_groups


class Command(BaseCommand):
    help = (
        "Read-only audit for duplicate live publish tasks that must be manually "
        "reconciled before publishing migration 0006."
    )

    def handle(self, *args, **options):
        groups = find_duplicate_live_publish_task_groups()
        if not groups:
            self.stdout.write(self.style.SUCCESS("No duplicate live publish tasks found."))
            return

        for index, tasks in enumerate(groups, start=1):
            details = ", ".join(
                f"task_id={task['id']} status={task['status']}" for task in tasks
            )
            self.stdout.write(f"Group {index}: {details}")
        raise CommandError(
            f"Found {len(groups)} duplicate live publish task group(s). "
            "Manually reconcile the listed task IDs before applying publishing "
            "migration 0006; this command made no changes."
        )
