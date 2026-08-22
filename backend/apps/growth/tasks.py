from celery import shared_task
from uuid import UUID

from apps.common.tenant_tasks import (
    TenantTaskError,
    TenantWorkResult,
    parse_tenant_organization_id,
    require_tenant_object,
    run_tenant_coordinator,
    tenant_task_context,
)
from apps.identity.models import Organization
from apps.common.tenancy import tenant_atomic
from apps.publishing.models import PublishTask

from .discovery import run_due_discovery_profiles
from .maps_discovery import run_due_maps_configs
from .agent.acquisition import run_proactive_acquisition, run_proactive_acquisition_day
from .models import GrowthPublishItem


def _parse_verification_id(value):
    if type(value) is not str or not value or value != value.strip():
        raise TenantTaskError("verification_id must be a valid UUID string.")
    try:
        return UUID(value)
    except ValueError as exc:
        raise TenantTaskError("verification_id must be a valid UUID string.") from exc


@shared_task
def run_email_verification(organization_id, verification_id):
    from .email_verification_services import execute_email_verification

    tenant_id = parse_tenant_organization_id(organization_id)
    run_id = _parse_verification_id(verification_id)
    result = execute_email_verification(
        organization_id=tenant_id,
        run_id=run_id,
    )
    return {
        "verification_id": str(result.id),
        "state": result.state,
        "result_status": result.result_status,
    }


@shared_task
def scan_due_discovery_profiles(limit=25):
    def scan_one(organization_id, remaining):
        result = run_due_discovery_profiles(
            organization_id=organization_id,
            limit=remaining,
        )
        return TenantWorkResult(consumed=result["scanned"], counters=result)

    result = run_tenant_coordinator(scan_one, limit=limit)
    return {key: result.get(key, 0) for key in ("scanned", "succeeded", "failed", "overlapping")}


@shared_task
def scan_due_maps_configs(limit=25):
    def scan_one(organization_id, remaining):
        result = run_due_maps_configs(
            organization_id=organization_id,
            limit=remaining,
        )
        return TenantWorkResult(consumed=result["scanned"], counters=result)

    result = run_tenant_coordinator(scan_one, limit=limit)
    return {key: result.get(key, 0) for key in ("scanned", "succeeded", "failed")}


@shared_task
def run_proactive_acquisition_task(organization_id, candidate_id, approvals=None):
    tenant_id = parse_tenant_organization_id(organization_id)
    organization = Organization.objects.get(pk=tenant_id)
    result = run_proactive_acquisition(
        organization=organization,
        candidate_id=candidate_id,
        approvals=set(approvals or []),
        organization_id=tenant_id,
    )
    return {
        "status": result.status,
        "pending_approval_token": (
            result.pending_approval.approval_token if result.pending_approval else None
        ),
    }


@shared_task
def run_due_proactive_acquisition(limit=50):
    def run_one(organization_id, remaining):
        organization = Organization.objects.get(pk=organization_id)
        result = run_proactive_acquisition_day(
            organization=organization,
            limit=remaining,
            organization_id=organization_id,
        )
        counters = {
            key: result[key]
            for key in ("candidates", "waiting_approval", "completed", "failed")
        }
        counters["organizations"] = int(result["candidates"] > 0)
        return TenantWorkResult(consumed=result["candidates"], counters=counters)

    result = run_tenant_coordinator(run_one, limit=limit)
    return {
        key: result.get(key, 0)
        for key in ("organizations", "candidates", "waiting_approval", "completed", "failed")
    }


@shared_task
def execute_growth_publish_item(organization_id, item_id):
    from .publishing import execute_growth_publish_item_phased

    tenant_id = parse_tenant_organization_id(organization_id)
    return execute_growth_publish_item_phased(
        item_id,
        organization_id=tenant_id,
    )


@shared_task
def sync_growth_publish_item_from_task(organization_id, task_id):
    from .publishing import sync_publish_item_from_task

    with tenant_task_context(organization_id) as tenant_id:
        require_tenant_object(PublishTask, tenant_id, pk=task_id)
        item = sync_publish_item_from_task(
            task_id=task_id,
            organization_id=tenant_id,
        )
        return {"item_id": str(item.id), "status": item.status} if item else None


@shared_task
def reconcile_delegated_publish_items(limit=200):
    from .publishing import sync_publish_item_from_task

    def reconcile_one(organization_id, remaining):
        with tenant_atomic(organization_id):
            task_ids = list(
                GrowthPublishItem.objects.filter(
                    organization_id=organization_id,
                    status=GrowthPublishItem.Status.DELEGATED,
                    publish_task__status__in=["SUCCEEDED", "FAILED", "CANCELED"],
                )
                .order_by("id")
                .values_list("publish_task_id", flat=True)[:remaining]
            )
            for task_id in task_ids:
                sync_publish_item_from_task(
                    task_id=str(task_id),
                    organization_id=organization_id,
                )
        count = len(task_ids)
        return TenantWorkResult(consumed=count, counters={"reconciled": count})

    return {
        "reconciled": run_tenant_coordinator(reconcile_one, limit=limit).get(
            "reconciled",
            0,
        )
    }
