import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIRun, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.campaigns.models import (
    Campaign, ContentBrief, ContentBriefPlatform, ContentBriefProduct,
    lifecycle_writes,
)
from apps.catalog.models import Product
from apps.content.services import (
    approve_content, create_generated_master, create_platform_content,
)
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.capabilities import CONNECTOR_CAPABILITIES
from apps.platforms.codes import AccountCapability
from apps.platforms.models import (
    ConnectorCredential, Platform, PlatformCapability, SocialAccount,
)


@pytest.fixture
def publishing_context(db, monkeypatch):
    monkeypatch.setattr(
        "apps.publishing.tasks.run_publish_task.delay",
        lambda _organization_id, _task_id: None,
    )
    organization = Organization.objects.create(name="Publishing Org", slug="publishing-org")
    actor = get_user_model().objects.create_user(username="publisher", password="x")
    campaign = Campaign.objects.create(organization=organization, name="Launch")
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
    platform = Platform.objects.create(code="MOCK", name="Mock Platform")
    product = Product.objects.create(
        organization=organization, name_en="Helical Gear", module_min=1,
        module_max=2, tooth_count_min=10, tooth_count_max=20,
        pressure_angle=20, moq=1, status=Product.Status.ACTIVE,
        manufacturing_capabilities=["Hobbing"],
        inspection_capabilities=["CMM"],
    )
    PlatformCapability.objects.create(
        platform=platform, code=AccountCapability.PUBLISH
    )
    ContentBriefPlatform.objects.create(
        organization=organization, brief=brief, platform=platform
    )
    ContentBriefProduct.objects.create(
        organization=organization, brief=brief, product=product
    )
    brief.status = ContentBrief.Status.READY
    with lifecycle_writes():
        brief.save(update_fields=["status", "updated_at"])
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": str(brief.id), "brief_version": brief.version},
        created_by=actor,
    )
    claimed = JobService.claim(worker_id="publishing-test", job_id=job.id)
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="publishing-test",
        provider="fake",
        model="fake-v1",
        template="test",
        output_schema={"type": "object"},
        status="PUBLISHED",
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
                "title": "Generated",
                "body": "Body",
                "cta": "Quote",
                "concept_codes": [],
            },
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
    master = create_generated_master(
        brief=brief, job=claimed, ai_run=run, actor=actor
    )
    JobService.succeed(
        job.id,
        claim_token=claimed.claim_token,
        result_reference={
            "type": "master_content", "id": str(master.id), "version": 1,
        },
    )
    master = approve_content(master, actor=actor)
    content = approve_content(
        create_platform_content(master, platform=platform, actor=actor), actor=actor
    )
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://mock/publisher",
        granted_scopes=[AccountCapability.PUBLISH],
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="mock-account",
        display_name="Mock Account",
        publish_mode=SocialAccount.PublishMode.API_AUTO,
    )
    CONNECTOR_CAPABILITIES[platform.code] = {AccountCapability.PUBLISH}
    yield {
        "organization": organization,
        "actor": actor,
        "campaign": campaign,
        "brief": brief,
        "platform": platform,
        "product": product,
        "content": content,
        "account": account,
    }
    CONNECTOR_CAPABILITIES.pop(platform.code, None)
