from copy import deepcopy
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from apps.ai.models import AIRun, PromptVersion
from apps.ai.orchestration import GenerationPreflightError, execute_generation_job
from apps.ai.services import PromptVersionService, scrub_secrets
from apps.content.payloads import CONTENT_OUTPUT_SCHEMA_V2
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
    concept_alpha = str(uuid4())
    concept_zeta = str(uuid4())
    return {
        "schema_version": "1.0",
        "organization_id": str(organization.id),
        "brief_id": str(uuid4()),
        "brief_version": 2,
        "campaign_id": str(uuid4()),
        "campaign_version": 3,
        "products": [{
            "product_id": str(uuid4()), "product_version": 4,
            "name_zh": "精密齿轮", "name_en": "Precision Gear",
            "module_min": "1.0000", "module_max": "2.0000",
            "tooth_count_min": 10, "tooth_count_max": 40,
            "pressure_angle": "20.000", "accuracy_grade": "ISO 6",
            "heat_treatment": "Carburized", "surface_treatment": "",
            "manufacturing_capabilities": ["hobbing"],
            "inspection_capabilities": ["CMM"], "moq": 1,
            "lead_time": "4 weeks", "landing_page_url": "https://example.com/product",
            "status": "ACTIVE",
            "concept_versions": [{
                "link_id": str(uuid4()), "link_version": 1, "role": "TYPE",
                "concept_id": concept_alpha, "concept_code": "ALPHA",
                "concept_type": "PRODUCT_TYPE", "concept_version": 1,
            }],
        }],
        "assets": [{
            "asset_id": str(uuid4()), "checksum": "a" * 64,
            "mime_type": "image/png", "asset_type": "IMAGE", "language": "en",
            "tags": ["gear"], "product_ids": [str(uuid4())],
        }],
        "target_country": "Germany",
        "customer_type": "Industrial buyer",
        "content_objective": "Generate leads",
        "cta": "Request a quote",
        "landing_page_url": "https://example.com/landing",
        "language": "en",
        "keywords": ["precision gear"],
        "prohibited_claims": ["zero wear"],
        "selling_points": ["Ground teeth"],
        "advantages": ["Short lead time"],
        "target_platforms": [{
            "platform_id": str(uuid4()), "code": "LINKEDIN", "name": "LinkedIn",
            "capability_codes": ["PUBLISH"],
        }],
        "ontology_snapshot": {
            "organization_id": str(organization.id),
            "concept_versions": [
                {"concept_id": concept_zeta, "code": "ZETA", "concept_type": "APPLICATION", "label_zh": "泽塔", "label_en": "Zeta", "status": "APPROVED", "version": 2},
                {"concept_id": concept_alpha, "code": "ALPHA", "concept_type": "PRODUCT_TYPE", "label_zh": "阿尔法", "label_en": "Alpha", "status": "APPROVED", "version": 1},
            ],
            "relation_versions": [{"relation_id": str(uuid4()), "subject_concept_id": concept_alpha, "predicate": "APPLIES_TO", "object_concept_id": concept_zeta, "status": "APPROVED", "version": 1}],
            "evidence_references": [{"evidence_id": str(uuid4()), "evidence_type": "HUMAN_ENTRY", "source_object_type": "", "source_object_id": None, "source_url": None, "excerpt": "Approved evidence", "captured_at": None, "status": "APPROVED", "version": 1}],
            "generated_at": "2026-08-09T08:00:00Z",
        },
        "generated_at": "2026-08-09T08:00:01Z",
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


@pytest.mark.django_db
def test_fake_generation_quotes_only_verified_fact_snapshot(
    organization, frozen_input, prompt
):
    frozen_input["verified_product_facts"] = [{
        "fact_id": str(uuid4()),
        "product_id": frozen_input["products"][0]["product_id"],
        "field_name": "process",
        "value": "Gear grinding",
        "category": "PROCESS",
        "source_asset_id": frozen_input["assets"][0]["asset_id"],
        "source_page": 1,
        "source_filename": "gear-catalog.pdf",
        "source_excerpt": "Process: Gear grinding",
        "is_demo": True,
    }]
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert "Verified facts: process=Gear grinding." in run.output_json["body"]


class CapturingContentProvider:
    def __init__(self):
        self.prompt = ""

    def generate(self, *, prompt, schema):
        self.prompt = prompt
        return {
            "title": "Captured",
            "body": "Captured body",
            "cta": "Request a quote",
            "concept_codes": ["ALPHA", "ZETA"],
        }


@pytest.mark.django_db
def test_generation_prompt_sends_the_complete_frozen_business_context(
    organization, frozen_input, prompt
):
    provider = CapturingContentProvider()
    provider_registry.register("capture-content", provider, replace=True)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    run = execute_generation_job(
        job.id,
        prompt_version_id=prompt.id,
        provider_code="capture-content",
    )

    assert run.status == AIRun.Status.SUCCEEDED
    instruction, separator, raw_input = provider.prompt.partition("||INPUT:")
    assert separator == "||INPUT:"
    assert "single publication language" in instruction
    assert "never include internal_translation_zh" in instruction.lower()
    sent = __import__("json").loads(raw_input)
    assert sent["language"] == "en"
    assert sent["customer_type"] == "Industrial buyer"
    assert sent["content_objective"] == "Generate leads"
    assert sent["landing_page_url"] == "https://example.com/landing"
    assert sent["prohibited_claims"] == ["zero wear"]
    assert sent["selling_points"] == ["Ground teeth"]
    assert sent["advantages"] == ["Short lead time"]
    assert sent["target_platforms"][0]["code"] == "LINKEDIN"


def test_scrub_secrets_recursively_without_mutating_source():
    source = {
        "api_key": "one",
        "Nested": [{"Authorization": "Bearer two", "safe": 3}],
        "private-key": "three",
        "TOKENS": ["four"],
        "github_auth_token": "five",
        "githubToken": "five-b",
        "serviceApiKeyValue": "six",
        "database-password-current": "seven",
        "session_cookie_data": "eight",
        "signing_private_key_pem": "nine",
        "public_token_count": 12,
        "password_policy": "strong",
        "safe_tokenized_name": "kept",
    }
    original = deepcopy(source)

    scrubbed = scrub_secrets(source)

    assert scrubbed == {
        "Nested": [{"safe": 3}], "public_token_count": 12,
        "password_policy": "strong", "safe_tokenized_name": "kept",
    }
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


def test_fake_v2_does_not_generate_an_unrequested_chinese_translation(frozen_input):
    prompt = "Create content||INPUT:" + __import__("json").dumps(frozen_input)

    result = FakeAIProvider().generate(prompt=prompt, schema=CONTENT_OUTPUT_SCHEMA_V2)

    assert result["language"] == "en"
    assert "internal_translation_zh" not in result


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

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    assert error.value.code == "invalid_generation_input"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0
    assert AIRun.objects.filter(job=job).count() == 0


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

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    assert error.value.code == "invalid_generation_input"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0
    assert AIRun.objects.filter(job=job).count() == 0


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

    job.refresh_from_db()
    assert run.error == {
        "code": "provider_error",
        "message": "AI provider generation failed.",
    }
    assert job.error == run.error
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


@pytest.mark.django_db
def test_result_writer_commits_before_job_success(organization, frozen_input, prompt):
    job = JobService.create(
        organization=organization, job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )
    content_id = uuid4()

    run = execute_generation_job(
        job.id,
        prompt_version_id=prompt.id,
        result_writer=lambda run, output: {"type": "master_content", "id": str(content_id)},
    )

    job.refresh_from_db()
    assert run.status == AIRun.Status.SUCCEEDED
    assert job.status == Job.Status.SUCCEEDED
    assert job.result_reference == {"type": "master_content", "id": str(content_id)}


@pytest.mark.django_db
def test_result_writer_failure_leaves_no_successful_job(organization, frozen_input, prompt):
    job = JobService.create(
        organization=organization, job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    def fail_writer(run, output):
        raise RuntimeError("content write failed")

    run = execute_generation_job(
        job.id, prompt_version_id=prompt.id, result_writer=fail_writer
    )

    job.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert job.status == Job.Status.FAILED
    assert job.result_reference is None


@pytest.mark.django_db
def test_prompt_and_provider_preflight_failure_does_not_claim_job(
    organization, frozen_input
):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=uuid4())

    job.refresh_from_db()
    assert error.value.code == "prompt_not_available"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0
    assert AIRun.objects.filter(job=job).count() == 0


@pytest.mark.django_db
def test_unknown_provider_is_rejected_before_claim(organization, frozen_input, prompt):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(
            job.id, prompt_version_id=prompt.id, provider_code="not-registered"
        )

    job.refresh_from_db()
    assert error.value.code == "provider_not_available"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0
    assert AIRun.objects.filter(job=job).count() == 0


@pytest.mark.django_db
def test_published_prompt_with_wrong_purpose_is_rejected_before_claim(
    organization, frozen_input
):
    wrong_prompt = PromptVersionService.create(
        purpose="KEYWORD_CLUSTER",
        code="wrong-purpose",
        provider="fake",
        model="fake-v1",
        template="{product_name}|{target_country}|{target_platform}|{cta}|{concept_codes}",
        output_schema=OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=wrong_prompt.id)

    job.refresh_from_db()
    assert error.value.code == "prompt_purpose_mismatch"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0
    assert AIRun.objects.filter(job=job).count() == 0


class CancelingProvider:
    def __init__(self, job_id, *, raises=False):
        self.job_id = job_id
        self.raises = raises

    def generate(self, *, prompt, schema):
        JobService.cancel(self.job_id)
        if self.raises:
            raise RuntimeError("late provider error")
        return FakeAIProvider().generate(prompt=prompt, schema=schema)


@pytest.mark.django_db
@pytest.mark.parametrize("raises", [False, True])
def test_late_provider_completion_converges_airun_to_canceled(
    organization, frozen_input, prompt, raises
):
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )
    code = f"canceling-{raises}"
    provider_registry.register(code, CancelingProvider(job.id, raises=raises), replace=True)

    run = execute_generation_job(
        job.id, prompt_version_id=prompt.id, provider_code=code
    )
    duplicate = execute_generation_job(
        job.id, prompt_version_id=prompt.id, provider_code=code
    )

    job.refresh_from_db()
    assert run.status == AIRun.Status.CANCELED
    assert run.output_json is None
    assert duplicate.pk == run.pk
    assert duplicate.status == AIRun.Status.CANCELED
    assert job.status == Job.Status.CANCELED
    assert job.attempts.get(number=1).status == "CANCELED"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("campaign_version"),
        lambda value: value["products"][0].pop("product_version"),
        lambda value: value["ontology_snapshot"].pop("generated_at"),
        lambda value: value["ontology_snapshot"]["relation_versions"][0].pop("relation_id"),
        lambda value: value["target_platforms"].clear(),
        lambda value: value.update({"unknown_provenance": "forged"}),
    ],
)
def test_incomplete_or_unknown_task8_snapshot_is_rejected_before_claim(
    organization, frozen_input, prompt, mutation
):
    mutation(frozen_input)
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    assert error.value.code == "invalid_generation_input"
    assert job.status == Job.Status.QUEUED
    assert job.attempts.count() == 0


@pytest.mark.django_db
def test_task8_snapshot_organization_must_match_job_and_ontology(
    organization, frozen_input, prompt
):
    frozen_input["ontology_snapshot"]["organization_id"] = str(uuid4())
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=frozen_input,
    )

    with pytest.raises(GenerationPreflightError) as error:
        execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert error.value.code == "generation_input_organization_mismatch"
