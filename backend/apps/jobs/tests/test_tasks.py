from uuid import uuid4

import pytest

from apps.ai.models import AIRun, PromptVersion
from apps.ai.services import PromptVersionService
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.jobs.tasks import execute_ai_job


@pytest.mark.django_db(transaction=True)
def test_celery_wrapper_delegates_to_real_orchestration():
    organization = Organization.objects.create(name="Task Org", slug="task-org")
    product_id = uuid4()
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="task-content",
        provider="fake",
        model="fake-v1",
        template="{product_name}|{target_country}|{target_platform}|{cta}|{concept_codes}",
        output_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "body": {"type": "string"},
                "cta": {"type": "string"},
                "concept_codes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "body", "cta", "concept_codes"],
            "additionalProperties": False,
        },
        status=PromptVersion.Status.PUBLISHED,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={
            "schema_version": "1.0",
            "organization_id": str(organization.id),
            "brief_id": str(uuid4()),
            "brief_version": 1,
            "campaign_id": str(uuid4()),
            "campaign_version": 1,
            "products": [{
                "product_id": str(product_id), "product_version": 1,
                "name_zh": "齿轮", "name_en": "Gear",
                "module_min": "1.0000", "module_max": "2.0000",
                "tooth_count_min": 10, "tooth_count_max": 20,
                "pressure_angle": "20.000", "accuracy_grade": "ISO 6",
                "heat_treatment": "", "surface_treatment": "",
                "manufacturing_capabilities": [], "inspection_capabilities": [],
                "moq": 1, "lead_time": "4 weeks", "landing_page_url": "",
                "status": "ACTIVE", "concept_versions": [],
            }],
            "assets": [{
                "asset_id": str(uuid4()), "checksum": "a" * 64,
                "mime_type": "image/png", "asset_type": "IMAGE",
                "language": "en", "tags": [],
                "product_ids": [str(product_id)],
            }],
            "target_country": "US",
            "customer_type": "Buyer",
            "content_objective": "Leads",
            "target_platforms": [{
                "platform_id": str(uuid4()), "code": "LINKEDIN",
                "name": "LinkedIn", "capability_codes": [],
            }],
            "cta": "Quote",
            "landing_page_url": "https://example.com",
            "language": "en",
            "keywords": [],
            "prohibited_claims": [],
            "selling_points": [],
            "advantages": [],
            "ontology_snapshot": {
                "organization_id": str(organization.id),
                "concept_versions": [], "relation_versions": [],
                "evidence_references": [],
                "generated_at": "2026-08-09T08:00:00Z",
            },
            "generated_at": "2026-08-09T08:00:01Z",
        },
    )

    result = execute_ai_job.delay(str(job.id), str(prompt.id)).get()

    assert result["status"] == AIRun.Status.SUCCEEDED
    assert AIRun.objects.filter(job=job).count() == 1
