import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.campaigns.models import (
    Campaign,
    ContentBrief,
    ContentBriefPlatform,
    lifecycle_writes,
)
from apps.content.models import PlatformContent
from apps.content.services import create_generated_master
from apps.content.tasks import generate_master_content_job
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform


@pytest.fixture
def master_with_two_platforms(db):
    organization = Organization.objects.create(
        name="Master Gen Org", slug="master-gen-org"
    )
    actor = get_user_model().objects.create_user(
        username="master-gen-actor", password="x"
    )
    campaign = Campaign.objects.create(organization=organization, name="MasterGen")
    brief = ContentBrief.objects.create(
        organization=organization,
        campaign=campaign,
        created_by=actor,
        status=ContentBrief.Status.DRAFT,
        target_country="DE",
        customer_type="Buyer",
        content_objective="Leads",
        cta="Quote",
        landing_page_url="https://example.com",
        language="en",
        selling_points=["Quality"],
        advantages=["Speed"],
        keywords=["gear"],
    )
    linkedin = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    facebook = Platform.objects.create(code="FACEBOOK", name="Facebook")
    for platform in (linkedin, facebook):
        ContentBriefPlatform.objects.create(
            organization=organization, brief=brief, platform=platform
        )
    brief.status = ContentBrief.Status.READY
    with lifecycle_writes():
        brief.save(update_fields=["status", "updated_at"])

    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="master-gen-test",
        provider="fake",
        model="fake-v1",
        template="test",
        output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={
            "brief_id": str(brief.id),
            "brief_version": brief.version,
            "verified_product_facts": [],
        },
        created_by=actor,
    )
    claimed = JobService.claim(worker_id="master-gen-test", job_id=job.id)
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
                "title": "Generated",
                "body": "Body",
                "cta": "Quote",
                "concept_codes": [],
            },
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
    master = create_generated_master(
        brief=brief, job=claimed, ai_run=run, actor=actor, auto_approve=True
    )
    JobService.succeed(
        job.id,
        claim_token=claimed.claim_token,
        result_reference={
            "type": "master_content",
            "id": str(master.id),
            "version": master.version,
        },
    )
    job.refresh_from_db()
    return organization, actor, master, job, prompt


@pytest.mark.django_db
def test_generate_master_content_job_creates_one_platform_per_selected(
    master_with_two_platforms,
):
    _, _, master, job, prompt = master_with_two_platforms

    generate_master_content_job(job.id, prompt.id)

    contents = PlatformContent.objects.filter(master_content=master)
    assert contents.count() == 2
    assert set(contents.values_list("platform__code", flat=True)) == {
        "LINKEDIN",
        "FACEBOOK",
    }
    assert set(contents.values_list("status", flat=True)) == {
        PlatformContent.Status.IN_REVIEW,
    }


@pytest.mark.django_db
def test_generate_master_content_job_is_idempotent(master_with_two_platforms):
    _, _, master, job, prompt = master_with_two_platforms

    generate_master_content_job(job.id, prompt.id)
    generate_master_content_job(job.id, prompt.id)

    assert PlatformContent.objects.filter(master_content=master).count() == 2


@pytest.mark.django_db
def test_generate_master_content_job_exposes_platform_failure(
    master_with_two_platforms, monkeypatch
):
    from apps.content import services

    _, _, master, job, prompt = master_with_two_platforms

    real_create = services.create_platform_content

    def fail_facebook(master_content, *, platform, actor=None):
        if platform.code == "FACEBOOK":
            raise services.ContentStateError("injected platform failure")
        return real_create(master_content, platform=platform, actor=actor)

    monkeypatch.setattr(services, "create_platform_content", fail_facebook)

    with pytest.raises(services.ContentStateError, match="injected platform failure"):
        generate_master_content_job(job.id, prompt.id)
