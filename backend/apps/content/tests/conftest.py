import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.campaigns.models import (
    Campaign, ContentBrief, ContentBriefPlatform, ContentBriefProduct, lifecycle_writes,
)
from apps.catalog.models import Product
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
    product = Product.objects.create(
        organization=organization, name_en="Precision gear",
        module_min="1.0000", module_max="2.0000",
        tooth_count_min=10, tooth_count_max=40, pressure_angle="20.000",
        manufacturing_capabilities=["hobbing"], inspection_capabilities=["CMM"],
        moq=1, status=Product.Status.ACTIVE,
    )
    ContentBriefProduct.objects.create(
        organization=organization, brief=brief, product=product,
    )
    brief.status = ContentBrief.Status.READY
    with lifecycle_writes():
        brief.save(update_fields=["status", "updated_at"])
    brief.refresh_from_db()
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={
            "brief_id": str(brief.id),
            "brief_version": brief.version,
            "verified_product_facts": [{
                "fact_id": "11111111-1111-4111-8111-111111111111",
                "product_id": "22222222-2222-4222-8222-222222222222",
                "field_name": "process",
                "value": "Gear grinding",
                "category": "PROCESS",
                "source_asset_id": "33333333-3333-4333-8333-333333333333",
                "source_filename": "gear-catalog.pdf",
                "source_page": 2,
                "source_excerpt": "Process: Gear grinding",
                "is_demo": True,
            }],
        },
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
    from apps.content.services import create_generated_master

    master = create_generated_master(
        brief=brief, job=claimed, ai_run=run, actor=actor
    )
    JobService.succeed(
        job.id, claim_token=claimed.claim_token,
        result_reference={
            "type": "master_content", "id": str(master.id), "version": 1,
        },
    )
    job.refresh_from_db()
    return organization, actor, brief, job, run
