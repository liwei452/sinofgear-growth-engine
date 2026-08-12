from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import AIRetryDispatchOutbox, AIRun, PromptVersion, ai_audit_writes
from apps.ai.tasks import dispatch_due_ai_retries
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("job_type", "target"),
    [
        (Job.Type.CONTENT_GENERATE, "apps.content.tasks.generate_master_content_job.delay"),
        (Job.Type.LEAD_ANALYZE, "apps.leads.tasks.execute_lead_analysis.delay"),
    ],
)
def test_dispatcher_recovers_due_retry_after_original_publish_crash(
    monkeypatch, job_type, target
):
    organization = Organization.objects.create(name=job_type, slug=job_type.lower())
    with ai_audit_writes():
        prompt = PromptVersion.objects.create(
            purpose=job_type, code=f"dispatch-{job_type}", provider="fake",
            model="fake", template="x", output_schema={"type": "object"},
            version=1, status=PromptVersion.Status.PUBLISHED,
        )
    job = JobService.create(
        organization=organization, job_type=job_type, input_snapshot={"safe": True}
    )
    claimed = JobService.claim(worker_id="crashed", job_id=job.id)
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization, job=claimed, job_attempt=1,
            prompt_version=prompt, provider="fake", model="fake",
            input_snapshot={"safe": True}, status=AIRun.Status.RUNNING,
            started_at=timezone.now(), next_retry_at=timezone.now() - timedelta(seconds=1),
        )
    AIRetryDispatchOutbox.objects.create(
        run=run, retry_generation=1,
        available_at=timezone.now() - timedelta(seconds=1),
    )
    sent = []
    monkeypatch.setattr(target, lambda *args: sent.append(args))

    first = dispatch_due_ai_retries()
    second = dispatch_due_ai_retries()

    run.refresh_from_db()
    assert first == {"dispatched": 1}
    assert second == {"dispatched": 0}
    assert sent == [(str(job.id), str(prompt.id))]
    outbox = AIRetryDispatchOutbox.objects.get(run=run)
    assert outbox.status == AIRetryDispatchOutbox.Status.DISPATCHING


@pytest.mark.django_db
def test_publish_exception_releases_outbox_for_retry(monkeypatch):
    organization = Organization.objects.create(name="Publish", slug="publish")
    with ai_audit_writes():
        prompt = PromptVersion.objects.create(
            purpose=Job.Type.CONTENT_GENERATE, code="publish", provider="fake",
            model="fake", template="x", output_schema={"type": "object"},
            version=1, status=PromptVersion.Status.PUBLISHED,
        )
    job = JobService.create(
        organization=organization, job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"safe": True},
    )
    claimed = JobService.claim(worker_id="crashed", job_id=job.id)
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization, job=claimed, job_attempt=1,
            prompt_version=prompt, provider="fake", model="fake",
            input_snapshot={}, status=AIRun.Status.RUNNING,
            started_at=timezone.now(), next_retry_at=timezone.now(),
        )
    outbox = AIRetryDispatchOutbox.objects.create(
        run=run, retry_generation=1, available_at=timezone.now(),
    )
    monkeypatch.setattr(
        "apps.content.tasks.generate_master_content_job.delay",
        lambda *_: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    assert dispatch_due_ai_retries() == {"dispatched": 0}
    outbox.refresh_from_db()
    assert outbox.status == AIRetryDispatchOutbox.Status.PENDING
    assert outbox.lease_token is None
