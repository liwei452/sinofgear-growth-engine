from celery import shared_task

from .discovery import run_due_discovery_profiles
from .maps_discovery import run_due_maps_configs
from .agent.acquisition import run_proactive_acquisition, run_proactive_acquisition_day
from .models import DiscoveryCandidate
from apps.identity.models import Organization


@shared_task
def scan_due_discovery_profiles(limit=25):
    return run_due_discovery_profiles(limit=limit)


@shared_task
def scan_due_maps_configs(limit=25):
    return run_due_maps_configs(limit=limit)


@shared_task
def run_proactive_acquisition_task(organization_id, candidate_id, approvals=None):
    organization = Organization.objects.get(pk=organization_id)
    result = run_proactive_acquisition(
        organization=organization,
        candidate_id=candidate_id,
        approvals=set(approvals or []),
    )
    return {
        "status": result.status,
        "pending_approval_token": (
            result.pending_approval.approval_token if result.pending_approval else None
        ),
    }


@shared_task
def run_due_proactive_acquisition(limit=50):
    candidate_org_ids = list(
        DiscoveryCandidate.objects.filter(status=DiscoveryCandidate.Status.ACCEPTED)
        .values_list("organization_id", flat=True)
        .distinct()
    )
    summary = {
        "organizations": 0,
        "candidates": 0,
        "waiting_approval": 0,
        "completed": 0,
        "failed": 0,
    }
    for organization in Organization.objects.filter(id__in=candidate_org_ids):
        result = run_proactive_acquisition_day(organization=organization, limit=limit)
        summary["organizations"] += 1
        summary["candidates"] += result["candidates"]
        summary["waiting_approval"] += result["waiting_approval"]
        summary["completed"] += result["completed"]
        summary["failed"] += result["failed"]
    return summary


@shared_task
def execute_growth_publish_item(item_id):
    from .publishing import _execute_item

    return _execute_item(item_id)


@shared_task
def sync_growth_publish_item_from_task(task_id):
    from .publishing import sync_publish_item_from_task

    item = sync_publish_item_from_task(task_id=task_id)
    return {"item_id": str(item.id), "status": item.status} if item else None


@shared_task
def reconcile_delegated_publish_items(limit=200):
    from .models import GrowthPublishItem
    from .publishing import sync_publish_item_from_task

    task_ids = list(
        GrowthPublishItem.objects.filter(
            status=GrowthPublishItem.Status.DELEGATED,
            publish_task__status__in=["SUCCEEDED", "FAILED", "CANCELED"],
        ).values_list("publish_task_id", flat=True)[:limit]
    )
    for task_id in task_ids:
        sync_publish_item_from_task(task_id=str(task_id))
    return {"reconciled": len(task_ids)}
