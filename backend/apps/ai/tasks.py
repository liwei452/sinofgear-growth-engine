from datetime import timedelta
from uuid import uuid4

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.jobs.models import Job

from .models import AIRetryDispatchOutbox


DISPATCH_LEASE_SECONDS = 60


@transaction.atomic
def _claim_due_outbox(limit=100):
    now = timezone.now()
    rows = list(
        AIRetryDispatchOutbox.objects.select_for_update(skip_locked=True)
        .filter(available_at__lte=now)
        .exclude(status=AIRetryDispatchOutbox.Status.ACKED)
        .select_related("run__job", "run__prompt_version")
        .order_by("available_at", "id")[:limit]
    )
    claimed = []
    for row in rows:
        if (
            row.status == AIRetryDispatchOutbox.Status.DISPATCHING
            and row.lease_expires_at and row.lease_expires_at > now
        ):
            continue
        row.status = AIRetryDispatchOutbox.Status.DISPATCHING
        row.lease_token = uuid4()
        row.lease_expires_at = now + timedelta(seconds=DISPATCH_LEASE_SECONDS)
        row.attempts += 1
        row.save(update_fields=[
            "status", "lease_token", "lease_expires_at", "attempts"
        ])
        claimed.append(row)
    return [(str(row.id), str(row.lease_token)) for row in claimed]


@transaction.atomic
def _release_dispatch(outbox_id, token):
    row = AIRetryDispatchOutbox.objects.select_for_update().get(pk=outbox_id)
    if row.status != row.Status.DISPATCHING or str(row.lease_token) != str(token):
        return
    row.status = row.Status.PENDING
    row.lease_token = None
    row.lease_expires_at = None
    row.save(update_fields=["status", "lease_token", "lease_expires_at"])


@shared_task
def dispatch_due_ai_retries():
    dispatched = 0
    for outbox_id, token in _claim_due_outbox():
        row = AIRetryDispatchOutbox.objects.select_related(
            "run__job", "run__prompt_version"
        ).get(pk=outbox_id)
        try:
            if row.run.job.type == Job.Type.CONTENT_GENERATE:
                from apps.content.tasks import generate_master_content_job

                generate_master_content_job.delay(
                    str(row.run.job_id), str(row.run.prompt_version_id)
                )
            elif row.run.job.type == Job.Type.LEAD_ANALYZE:
                from apps.leads.tasks import execute_lead_analysis

                execute_lead_analysis.delay(
                    str(row.run.job_id), str(row.run.prompt_version_id)
                )
            else:
                _release_dispatch(outbox_id, token)
                continue
        except Exception:
            _release_dispatch(outbox_id, token)
            continue
        # A successful publish is not an acknowledgement. The consumer acks the
        # row atomically when it claims the durable provider call.
        dispatched += 1
    return {"dispatched": dispatched}
