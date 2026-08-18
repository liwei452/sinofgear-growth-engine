from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai.models import AIRun, OrganizationAIProviderConfig, PromptVersion, ai_audit_writes
from apps.ai.services import (
    AIBudgetExceeded,
    PromptVersionService,
    assert_ai_budget_available,
    estimate_deepseek_cost_micros,
    organization_daily_token_usage,
    reserve_ai_budget,
    reserve_ai_cost,
    settle_ai_budget,
    settle_ai_cost,
)
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


@pytest.fixture
def organization(db):
    return Organization.objects.create(
        name="Budget Org",
        slug="budget-org",
        ai_daily_token_budget=100,
    )


@pytest.fixture
def job(organization):
    return JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"brief_id": "b"},
        idempotency_key="budget-job",
    )


@pytest.fixture
def prompt():
    return PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="budget-prompt",
        provider="fake",
        model="fake-v1",
        template="test",
        output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )


def test_organization_daily_token_usage_sums_succeeded_runs(organization, job, prompt):
    with ai_audit_writes():
        AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=1,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot={},
            status=AIRun.Status.SUCCEEDED,
            started_at=timezone.now(),
            provider_metadata={
                "provider_code": "fake",
                "usage": {"total_tokens": 70},
            },
        )

    assert organization_daily_token_usage(organization.id) == 70


def test_assert_ai_budget_available_blocks_when_exceeded(organization, job, prompt):
    with ai_audit_writes():
        AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=1,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot={},
            status=AIRun.Status.SUCCEEDED,
            started_at=timezone.now(),
            provider_metadata={
                "provider_code": "fake",
                "usage": {"total_tokens": 100},
            },
        )

    with pytest.raises(AIBudgetExceeded):
        assert_ai_budget_available(organization)


def test_assert_ai_budget_available_ignores_old_runs(organization, job, prompt):
    with ai_audit_writes():
        AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=1,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot={},
            status=AIRun.Status.SUCCEEDED,
            started_at=timezone.now() - timedelta(days=2),
            provider_metadata={
                "provider_code": "fake",
                "usage": {"total_tokens": 999},
            },
        )

    assert_ai_budget_available(organization)


def test_reserve_and_settle_ai_budget_tokens(organization):
    organization.ai_daily_token_budget = 100
    organization.save(update_fields=["ai_daily_token_budget"])

    reserve_ai_budget(organization, tokens=60)
    organization.refresh_from_db()
    assert organization.ai_daily_reserved_tokens == 60

    with pytest.raises(AIBudgetExceeded):
        reserve_ai_budget(organization, tokens=50)

    settle_ai_budget(organization, tokens=60)
    organization.refresh_from_db()
    assert organization.ai_daily_reserved_tokens == 0


def test_deepseek_cost_estimate_uses_the_versioned_conservative_prices():
    assert estimate_deepseek_cost_micros(
        "deepseek-chat",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 1_370_000
    assert estimate_deepseek_cost_micros(
        "deepseek-reasoner",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    ) == 2_740_000


@pytest.mark.django_db
def test_reserve_and_settle_estimated_usd_budget_without_replacing_token_guard(organization):
    config = OrganizationAIProviderConfig.objects.create(
        organization=organization,
        model="deepseek-chat",
        daily_budget_micros=2_000_000,
    )

    reserved = reserve_ai_cost(
        organization,
        model="deepseek-chat",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert reserved == 1_370_000
    config.refresh_from_db()
    assert config.daily_reserved_micros == 1_370_000

    actual = settle_ai_cost(
        organization,
        reserved_micros=reserved,
        model="deepseek-chat",
        usage={"prompt_tokens": 500_000, "completion_tokens": 100_000},
    )
    assert actual == 245_000
    config.refresh_from_db()
    assert config.daily_reserved_micros == 0
    assert config.daily_spent_micros == 245_000
    organization.refresh_from_db()
    assert organization.ai_daily_token_budget == 100


@pytest.mark.django_db
def test_estimated_usd_budget_rejects_before_reserving(organization):
    config = OrganizationAIProviderConfig.objects.create(
        organization=organization,
        model="deepseek-chat",
        daily_budget_micros=100,
    )

    with pytest.raises(AIBudgetExceeded):
        reserve_ai_cost(
            organization,
            model="deepseek-chat",
            input_tokens=0,
            output_tokens=100,
        )

    config.refresh_from_db()
    assert config.daily_reserved_micros == 0
