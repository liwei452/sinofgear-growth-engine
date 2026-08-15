from celery import shared_task

from .discovery import run_due_discovery_profiles


@shared_task
def scan_due_discovery_profiles(limit=25):
    return run_due_discovery_profiles(limit=limit)

