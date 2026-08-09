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
            "products": [{"name_en": "Gear"}], "target_country": "US",
            "target_platforms": [{"code": "LINKEDIN"}], "cta": "Quote",
            "ontology_snapshot": {
                "concept_versions": [], "relation_versions": [], "evidence_references": []
            },
        },
    )

    result = execute_ai_job.delay(str(job.id), str(prompt.id)).get()

    assert result["status"] == AIRun.Status.SUCCEEDED
    assert AIRun.objects.filter(job=job).count() == 1
