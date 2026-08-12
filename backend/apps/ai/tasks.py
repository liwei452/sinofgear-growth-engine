from uuid import uuid4

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.jobs.models import Job

from .models import AIProviderCall, AIRun, ai_audit_writes


@transaction.atomic
def _claim_due_runs(limit=100):
    now = timezone.now()
    runs = list(
        AIRun.objects.select_for_update(skip_locked=True)
        .filter(status=AIRun.Status.RUNNING, next_retry_at__lte=now,
                retry_dispatch_token__isnull=True)
        .select_related("job", "prompt_version")
        .order_by("next_retry_at", "id")[:limit]
    )
    claimed = []
    for run in runs:
        active = AIProviderCall.objects.filter(
            run=run, status=AIProviderCall.Status.CALLING,
            lease_expires_at__gt=now,
        ).exists()
        if active:
            continue
        run.retry_dispatch_token = uuid4()
        with ai_audit_writes():
            run.save(update_fields=["retry_dispatch_token"])
        claimed.append((str(run.id), str(run.job_id), str(run.prompt_version_id), run.job.type))
    return claimed


@shared_task
def dispatch_due_ai_retries():
    dispatched = 0
    for run_id, job_id, prompt_id, job_type in _claim_due_runs():
        if job_type == Job.Type.CONTENT_GENERATE:
            from apps.content.tasks import generate_master_content_job

            generate_master_content_job.delay(job_id, prompt_id)
        elif job_type == Job.Type.LEAD_ANALYZE:
            from apps.leads.tasks import execute_lead_analysis

            execute_lead_analysis.delay(job_id, prompt_id)
        else:
            continue
        dispatched += 1
        with transaction.atomic():
            run = AIRun.objects.select_for_update().get(pk=run_id)
            run.next_retry_at = None
            run.retry_dispatch_token = None
            with ai_audit_writes():
                run.save(update_fields=["next_retry_at", "retry_dispatch_token"])
    return {"dispatched": dispatched}
