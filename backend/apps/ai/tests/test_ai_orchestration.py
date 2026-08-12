from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.ai.models import (
    AIExecutionIntent,
    AIProviderCall,
    AIProviderConfiguration,
    AIRun,
    AIUsageAttempt,
    PromptVersion,
    ai_audit_writes,
)
from apps.ai.orchestration import (
    GenerationPreflightError,
    ProviderRetryRequired,
    execute_generation_job,
)
from apps.ai.services import PromptVersionService, scrub_secrets
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService
from integrations.ai.providers import (
    FakeAIProvider,
    ProviderAuthenticationError,
    ProviderInvalidOutputError,
    ProviderRateLimitError,
    ProviderResult,
    provider_registry,
)


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
    assert first.output == {
        "title": "Precision Gear for Germany on LINKEDIN",
        "body": "Precision Gear for Germany. Approved concepts: ALPHA, ZETA.",
        "cta": "Request a quote",
        "concept_codes": ["ALPHA", "ZETA"],
    }


def _deepseek_job(organization, frozen_input, prompt, *, max_attempts=3):
    AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
        key_suffix="safe",
        daily_budget_usd="10.00",
    )
    routing = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "thinking_enabled": False,
        "policy_code": "deepseek-routing-v1",
        "policy_version": 1,
        "override_reason": "",
        "max_output_tokens": 1200,
        "timeout_seconds": 30,
    }
    snapshot = {**deepcopy(frozen_input), "ai_routing": routing}
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=snapshot,
        max_attempts=max_attempts,
    )
    rendered = "Precision Gear|Germany|LINKEDIN|Request a quote|ALPHA, ZETA"
    AIExecutionIntent.objects.create(
        job=job,
        organization=organization,
        provider="deepseek",
        model="deepseek-v4-flash",
        thinking_enabled=False,
        policy_code="deepseek-routing-v1",
        policy_version=1,
        override_reason="",
        max_output_tokens=1200,
        timeout_seconds=30,
        estimated_input_tokens=100,
        reserved_cost_usd="0.001000",
        provider_prompt=rendered,
        provider_schema=OUTPUT_SCHEMA,
        prompt_purpose="CONTENT_GENERATE",
        prompt_version_id_snapshot=prompt.id,
    )
    prompt.provider = "deepseek"
    prompt.model = "deepseek-v4-flash"
    # Prompt versions are immutable through services; this fixture intentionally
    # creates its DeepSeek identity through the protected audit write boundary.
    from apps.ai.models import ai_audit_writes
    with ai_audit_writes():
        prompt.save(update_fields=["provider", "model"])
    return job


class ResultProvider:
    def __init__(self, results):
        self.results = list(results)
        self.executions = []
        self.prompts = []

    def generate(self, *, prompt, schema, execution):
        del schema
        self.executions.append(execution)
        self.prompts.append(prompt)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.django_db
def test_deepseek_uses_frozen_intent_and_reconciles_safe_metadata(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider = ResultProvider([
        ProviderResult(
            output={
                "title": "Safe", "body": "Body", "cta": "Act",
                "concept_codes": ["ALPHA"],
            },
            metadata={
                "model": "deepseek-v4-flash", "request_id": "req-safe",
                "finish_reason": "stop", "input_tokens": 20,
                "output_tokens": 10, "cache_hit_tokens": 5,
                "duration_ms": 12, "reasoning_content": "must disappear",
            },
        )
    ])
    provider_registry.register("deepseek", provider, replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert run.status == AIRun.Status.SUCCEEDED
    assert provider.executions[0].model == "deepseek-v4-flash"
    assert provider.executions[0].thinking_enabled is False
    assert run.model == "deepseek-v4-flash"
    assert run.provider_metadata == {
        "provider_code": "deepseek", "model": "deepseek-v4-flash",
        "request_id": "req-safe", "finish_reason": "stop",
        "input_tokens": 20, "output_tokens": 10, "cache_hit_tokens": 5,
        "duration_ms": 12,
    }
    usage = AIUsageAttempt.objects.get(run=run)
    assert usage.status == AIUsageAttempt.Status.SUCCEEDED
    assert usage.input_tokens == 20
    assert usage.additional_reserved_usd == 0
    assert "reasoning" not in str(AIRun.objects.values()).lower()
    call = AIProviderCall.objects.get(run=run)
    assert call.status == AIProviderCall.Status.SUCCEEDED
    assert call.request_id == "req-safe"


@pytest.mark.django_db
def test_execution_uses_submission_frozen_prompt_and_schema_after_prompt_changes(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    original_prompt = job.ai_execution_intent.provider_prompt
    with ai_audit_writes():
        PromptVersion.objects.filter(pk=prompt.pk).update(
            template="MUTATED {product_name}", output_schema={"type": "string"}
        )

    class Capturing(ResultProvider):
        def generate(self, *, prompt, schema, execution):
            self.prompt = prompt
            self.schema = schema
            return super().generate(prompt=prompt, schema=schema, execution=execution)

    provider = Capturing([ProviderResult(
        output={"title": "Safe", "body": "Body", "cta": "Act", "concept_codes": ["ALPHA"]},
        metadata={"model": "deepseek-v4-flash", "input_tokens": 1,
                  "output_tokens": 1, "cache_hit_tokens": 0},
    )])
    provider_registry.register("deepseek", provider, replace=True)

    execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert provider.prompt == original_prompt
    assert provider.schema == OUTPUT_SCHEMA


@pytest.mark.django_db
def test_active_provider_call_lease_blocks_duplicate_delivery_before_network(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    claimed = JobService.claim(worker_id="first", job_id=job.id)
    from apps.ai.orchestration import _create_run
    audit = _create_run(
        job=claimed, prompt=prompt, provider="deepseek",
        model="deepseek-v4-flash", input_snapshot=claimed.input_snapshot,
    )
    AIProviderCall.objects.create(
        run=audit, generation=1, status=AIProviderCall.Status.CALLING,
        lease_token=uuid4(), lease_expires_at=timezone.now() + timedelta(minutes=2),
        reserved_usd="0.001000",
    )
    provider = ResultProvider([])
    provider_registry.register("deepseek", provider, replace=True)

    returned = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert returned.pk == audit.pk
    assert provider.executions == []


@pytest.mark.django_db
def test_deepseek_budget_failure_happens_before_provider_call(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    AIProviderConfiguration.objects.filter(organization=organization).update(
        daily_budget_usd="0.00"
    )
    provider = ResultProvider([])
    provider_registry.register("deepseek", provider, replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert provider.executions == []
    assert run.status == AIRun.Status.FAILED
    assert run.error["code"] == "deepseek_daily_budget_exceeded"


@pytest.mark.django_db
def test_retryable_provider_error_persists_bounded_retry_without_terminalizing(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider = ResultProvider([ProviderRateLimitError(retry_after_seconds=999999)])
    provider_registry.register("deepseek", provider, replace=True)

    with pytest.raises(ProviderRetryRequired) as retry:
        execute_generation_job(job.id, prompt_version_id=prompt.id)

    run = AIRun.objects.get(job=job)
    job.refresh_from_db()
    assert retry.value.countdown <= 300
    assert run.status == AIRun.Status.RUNNING
    assert run.transport_retry_count == 1
    assert run.next_retry_at is not None
    assert job.status == Job.Status.RUNNING
    assert AIUsageAttempt.objects.get(run=run).status == AIUsageAttempt.Status.RESERVED


@pytest.mark.django_db
def test_retryable_provider_error_stops_after_two_persisted_retries(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider = ResultProvider([
        ProviderRateLimitError(), ProviderRateLimitError(), ProviderRateLimitError()
    ])
    provider_registry.register("deepseek", provider, replace=True)

    for expected in (1, 2):
        with pytest.raises(ProviderRetryRequired) as retry:
            execute_generation_job(job.id, prompt_version_id=prompt.id)
        assert retry.value.retry_count == expected
        with ai_audit_writes():
            AIRun.objects.filter(job=job).update(next_retry_at=timezone.now())

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert run.status == AIRun.Status.FAILED
    assert run.transport_retry_count == 2
    assert run.error["code"] == "provider_rate_limited"
    assert len(provider.executions) == 3
    assert AIUsageAttempt.objects.get(run=run).status == AIUsageAttempt.Status.FAILED


class CancelingResultProvider(ResultProvider):
    def __init__(self, job_id, result):
        super().__init__([result])
        self.job_id = job_id

    def generate(self, *, prompt, schema, execution):
        JobService.cancel(self.job_id)
        return super().generate(prompt=prompt, schema=schema, execution=execution)


@pytest.mark.django_db
def test_cancellation_after_reservation_releases_budget_and_discards_result(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    result = ProviderResult(
        output={
            "title": "Late", "body": "Late", "cta": "Late",
            "concept_codes": ["ALPHA"],
        },
        metadata={"model": "deepseek-v4-flash", "input_tokens": 1,
                  "output_tokens": 1, "cache_hit_tokens": 0},
    )
    provider = CancelingResultProvider(job.id, result)
    provider_registry.register("deepseek", provider, replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    usage = AIUsageAttempt.objects.get(run=run)
    assert run.status == AIRun.Status.CANCELED
    assert run.output_json is None
    assert usage.status == AIUsageAttempt.Status.FAILED
    assert usage.actual_usd > 0
    assert usage.actual_usd < usage.reserved_usd
    usage.usage_day.refresh_from_db()
    assert usage.usage_day.reserved_usd == 0


@pytest.mark.django_db
def test_invalid_output_gets_one_safe_repair_using_same_intent(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider = ResultProvider([
        ProviderInvalidOutputError(),
        ProviderResult(
            output={
                "title": "Fixed", "body": "Body", "cta": "Act",
                "concept_codes": ["ALPHA"],
            },
            metadata={
                "model": "deepseek-v4-flash", "input_tokens": 20,
                "output_tokens": 10, "cache_hit_tokens": 0,
            },
        ),
    ])
    provider_registry.register("deepseek", provider, replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert run.status == AIRun.Status.SUCCEEDED
    assert run.repair_attempted is True
    assert len(provider.executions) == 2
    assert provider.executions[0] == provider.executions[1]
    assert provider.prompts[0] != provider.prompts[1]
    assert "REPAIR_INSTRUCTION" in provider.prompts[1]
    assert "invalid" not in provider.prompts[1].lower()
    usage = AIUsageAttempt.objects.get(run=run)
    reserved = Decimal(str(job.ai_execution_intent.reserved_cost_usd))
    assert usage.additional_reserved_usd == reserved
    assert usage.actual_usd > reserved


@pytest.mark.django_db
def test_authentication_failure_is_fixed_and_never_retried(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider = ResultProvider([ProviderAuthenticationError("key=do-not-store")])
    provider_registry.register("deepseek", provider, replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    assert run.status == AIRun.Status.FAILED
    assert run.error["code"] == "provider_authentication_failed"
    assert "do-not-store" not in str(AIRun.objects.values())


@pytest.mark.django_db
def test_huge_usage_metadata_is_not_persisted_and_fails_with_controlled_code(
    organization, frozen_input, prompt
):
    job = _deepseek_job(organization, frozen_input, prompt)
    provider_registry.register("deepseek", ResultProvider([ProviderResult(
        output={"title": "Safe", "body": "Body", "cta": "Act", "concept_codes": ["ALPHA"]},
        metadata={"model": "deepseek-v4-flash", "input_tokens": 2**80,
                  "output_tokens": 2**80, "cache_hit_tokens": 0,
                  "duration_ms": 2**80},
    )]), replace=True)

    run = execute_generation_job(job.id, prompt_version_id=prompt.id)

    job.refresh_from_db()
    usage = AIUsageAttempt.objects.get(run=run)
    call = AIProviderCall.objects.get(run=run)
    usage.usage_day.refresh_from_db()
    assert run.status == AIRun.Status.FAILED
    assert job.status == Job.Status.FAILED
    assert run.error["code"] == "deepseek_invalid_usage"
    assert (call.input_tokens, call.output_tokens, call.duration_ms) == (0, 0, 0)
    assert usage.reconciled_at is not None
    assert usage.actual_usd <= usage.reserved_usd + usage.additional_reserved_usd
    assert usage.usage_day.reserved_usd == 0


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
        return ProviderResult(
            output={"title": "missing required fields"}, metadata={}
        )


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
