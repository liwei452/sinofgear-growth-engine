from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
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
    sent = []
    monkeypatch.setattr(target, lambda *args: sent.append(args))

    first = dispatch_due_ai_retries()
    second = dispatch_due_ai_retries()

    run.refresh_from_db()
    assert first == {"dispatched": 1}
    assert second == {"dispatched": 0}
    assert sent == [(str(job.id), str(prompt.id))]
    assert run.next_retry_at is None
