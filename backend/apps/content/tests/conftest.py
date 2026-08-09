import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.campaigns.models import (
    Campaign, ContentBrief, ContentBriefPlatform, lifecycle_writes,
)
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform


@pytest.fixture
def content_provenance(db):
    organization = Organization.objects.create(name="Content Org", slug="content-org")
    actor = get_user_model().objects.create_user(username="content-actor", password="x")
    campaign = Campaign.objects.create(organization=organization, name="Content")
    brief = ContentBrief.objects.create(
        organization=organization,
        campaign=campaign,
        created_by=actor,
        status=ContentBrief.Status.DRAFT,
        target_country="US",
        customer_type="Buyer",
        content_objective="Leads",
        cta="Quote",
        landing_page_url="https://example.com",
        language="en",
        selling_points=["Quality"],
        advantages=["Speed"],
        keywords=["gear"],
    )
    selected_platform = Platform.objects.create(code="SELECTED", name="Selected")
    ContentBriefPlatform.objects.create(
        organization=organization, brief=brief, platform=selected_platform
    )
    brief.status = ContentBrief.Status.READY
    with lifecycle_writes():
        brief.save(update_fields=["status", "updated_at"])
    brief.refresh_from_db()
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": str(brief.id), "brief_version": brief.version},
        created_by=actor,
    )
    claimed = JobService.claim(worker_id="content-test", job_id=job.id)
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE", code="content-test", provider="fake", model="fake-v1",
        template="test", output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=job.attempt,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot=job.input_snapshot,
            status=AIRun.Status.SUCCEEDED,
            output_json={
                "title": "Generated", "body": "Body", "cta": "Quote",
                "concept_codes": [],
            },
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
    JobService.succeed(
        job.id, claim_token=claimed.claim_token,
        result_reference={"ai_run_id": str(run.id)},
    )
    job.refresh_from_db()
    return organization, actor, brief, job, run
