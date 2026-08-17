from celery import shared_task

from .discovery import run_due_discovery_profiles
from .maps_discovery import run_due_maps_configs
from .agent.acquisition import run_proactive_acquisition
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
