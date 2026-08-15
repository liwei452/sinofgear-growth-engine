from celery import shared_task

from .discovery import run_due_discovery_profiles
from .maps_discovery import run_due_maps_configs


@shared_task
def scan_due_discovery_profiles(limit=25):
    return run_due_discovery_profiles(limit=limit)


@shared_task
def scan_due_maps_configs(limit=25):
    return run_due_maps_configs(limit=limit)
