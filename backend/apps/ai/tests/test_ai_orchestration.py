from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError

from apps.ai.models import AIRun, PromptVersion
from apps.ai.orchestration import execute_generation_job
from apps.ai.services import PromptVersionService, scrub_secrets
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from integrations.ai.providers import FakeAIProvider, provider_registry


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "cta": {"type": "string"},
        "concept_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "body", "cta", "concept_codes"],
    "additionalProperties": False,
}


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="AI Org", slug="ai-org")


@pytest.fixture
def frozen_input(organization):
    return {
        "organization_id": str(organization.id),
        "brief_id": "brief-1",
        "products": [{"name_en": "Precision Gear"}],
        "target_country": "Germany",
        "target_platforms": [{"code": "LINKEDIN"}],
        "cta": "Request a quote",
        "ontology_snapshot": {
            "concept_versions": [
                {"code": "ZETA", "status": "APPROVED", "version": 2},
                {"code": "ALPHA", "status": "APPROVED", "version": 1},
            ],
            "relation_versions": [{"status": "APPROVED", "version": 1}],
            "evidence_references": [{"status": "APPROVED", "version": 1}],
        },
        "nested": {"Api-Key": "secret", "safe": [{"PASSWORD": "hidden", "x": 1}]},
    }


@pytest.fixture
def prompt():
    return PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="default-content",
        provider="fake",
        model="fake-v1",
        template="{product_name}|{target_country}|{target_platform}|{cta}|{concept_codes}",
        output_schema=OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
    )


def test_scrub_secrets_recursively_without_mutating_source():
    source = {
        "api_key": "one",
        "Nested": [{"Authorization": "Bearer two", "safe": 3}],
        "private-key": "three",
        "TOKENS": ["four"],
        "safe_tokenized_name": "kept",
    }
    original = deepcopy(source)

    scrubbed = scrub_secrets(source)

    assert scrubbed == {"Nested": [{"safe": 3}], "safe_tokenized_name": "kept"}
    assert source == original


@pytest.mark.django_db
def test_prompt_versions_are_immutable_and_not_deletable(prompt):
    prompt.template = "changed"
    with pytest.raises(ValidationError):
        prompt.save(update_fields=["template"])
    with pytest.raises(ValidationError):
        PromptVersion._base_manager.filter(pk=prompt.pk).update(model="other")
    with pytest.raises(ValidationError):
        prompt.delete()


def test_fake_ai_is_deterministic_and_uses_sorted_approved_codes(frozen_input):
    provider = FakeAIProvider()
    prompt_text = "Precision Gear|Germany|LINKEDIN|Request a quote|ALPHA, ZETA"

    first = provider.generate(prompt=prompt_text, schema=OUTPUT_SCHEMA)
    second = provider.generate(prompt=prompt_text, schema=OUTPUT_SCHEMA)

    assert first == second
    assert first == {
        "title": "Precision Gear for Germany on LINKEDIN",
        "body": "Precision Gear for Germany. Approved concepts: ALPHA, ZETA.",
        "cta": "Request a quote",
        "concept_codes": ["ALPHA", "ZETA"],
    }


@pytest.mark.django_db
def test_successful_run_freezes_scrubbed_input_and_completes_job(
    organization, frozen_input, prompt
):
    source = deepcopy(frozen_input)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=source,
    )

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)
    source["products"][0]["name_en"] = "Mutated later"

    job.refresh_from_db()
    assert run.status == AIRun.Status.SUCCEEDED
    assert run.input_snapshot["products"][0]["name_en"] == "Precision Gear"
    assert "Api-Key" not in run.input_snapshot["nested"]
    assert run.prompt_version_id == prompt.id
    assert run.provider == "fake"
    assert run.model == "fake-v1"
    assert run.output_json["concept_codes"] == ["ALPHA", "ZETA"]
    assert str(run.confidence) == "1.0000"
    assert run.provider_metadata == {"provider_code": "fake"}
    assert run.finished_at is not None
    assert job.status == Job.Status.SUCCEEDED


@pytest.mark.django_db
def test_corrupt_snapshot_with_disallowed_knowledge_fails_closed(
    organization, frozen_input, prompt
):
    frozen_input["ontology_snapshot"]["concept_versions"][0]["status"] = "DEPRECATED"
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert run.output_json is None
    assert job.status == Job.Status.FAILED
    assert job.error["code"] == "invalid_ontology_snapshot"


@pytest.mark.django_db
def test_missing_required_prompt_input_fails_with_controlled_error(
    organization, frozen_input, prompt
):
    frozen_input["products"] = []
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert run.error["code"] == "invalid_prompt_input"
    assert job.status == Job.Status.FAILED


class InvalidProvider:
    def generate(self, *, prompt, schema):
        return {"title": "missing required fields"}


class RaisingProvider:
    def generate(self, *, prompt, schema):
        raise RuntimeError("api_key=do-not-persist")


@pytest.mark.django_db
def test_invalid_provider_output_fails_run_and_job(organization, frozen_input, prompt):
    provider_registry.register("invalid-test", InvalidProvider(), replace=True)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    run = execute_generation_job(
        job.id, prompt_version_id=prompt.id, provider_code="invalid-test"
    )

    job.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert run.output_json is None
    assert run.error["code"] == "invalid_provider_output"
    assert job.status == Job.Status.FAILED


@pytest.mark.django_db
def test_provider_exception_is_normalized_without_secret_details(
    organization, frozen_input, prompt
):
    provider_registry.register("raising-test", RaisingProvider(), replace=True)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )
    run = execute_generation_job(
        job.id, prompt_version_id=prompt.id, provider_code="raising-test"
    )

    assert run.error == {
        "code": "provider_error",
        "message": "AI provider generation failed.",
    }
    assert "do-not-persist" not in str(run.error)


@pytest.mark.django_db
def test_ai_run_identity_output_and_history_reject_direct_mutation_and_delete(
    organization, frozen_input, prompt
):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )
    run = execute_generation_job(job.id, prompt_version_id=prompt.id)
    with pytest.raises(ValidationError):
        AIRun.objects.filter(pk=run.pk).update(output_json={"forged": True})
    with pytest.raises(ValidationError):
        AIRun._base_manager.bulk_update([run], ["provider"])
    with pytest.raises(ValidationError):
        run.delete()


@pytest.mark.django_db
def test_duplicate_delivery_does_not_create_second_successful_run(
    organization, frozen_input, prompt
):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )
    first = execute_generation_job(job.id, prompt_version_id=prompt.id)
    second = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert second.pk == first.pk
    assert AIRun.objects.filter(job=job, status=AIRun.Status.SUCCEEDED).count() == 1
