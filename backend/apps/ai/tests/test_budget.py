from datetime import UTC, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone

from apps.ai.budget import BudgetExceeded, reconcile_usage, reserve_budget
from apps.ai.models import (
    AIRun,
    AIProviderConfiguration,
    AIUsageAttempt,
    AIUsageDay,
    PromptVersion,
    ai_audit_writes,
)
from apps.ai.routing import create_execution_intent, route_ai_work
from apps.ai.services import PromptVersionService
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _context(*, budget="10.00", max_output=1200):
    organization = Organization.objects.create(name=f"Budget {budget}", slug=f"budget-{budget.replace('.', '-')}")
    user = get_user_model().objects.create_user(username=f"budget-{budget.replace('.', '-')}")
    AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
        key_suffix="safe",
        daily_budget_usd=Decimal(budget),
        flash_max_output_tokens=max_output,
    )
    snapshot = {"organization_id": str(organization.id), "text": "x" * 50}
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=snapshot,
        idempotency_key=f"budget-{budget}",
        created_by=user,
    )
    intent = create_execution_intent(
        job=job,
        decision=route_ai_work(job_type=job.type, snapshot=snapshot),
        created_by=user,
    )
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code=f"budget-{budget}",
        provider="deepseek",
        model=intent.model,
        template="{input_json}",
        output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=1,
            prompt_version=prompt,
            provider=intent.provider,
            model=intent.model,
            input_snapshot=snapshot,
            status=AIRun.Status.RUNNING,
            started_at=timezone.now(),
        )
    return organization, intent, run


@pytest.mark.django_db
def test_reservation_is_idempotent_and_uses_organization_utc_day(monkeypatch):
    organization, intent, run = _context()
    instant = datetime(2026, 8, 13, 7, 59, 59, tzinfo=dt_timezone(timedelta(hours=8)))
    monkeypatch.setattr("apps.ai.budget.timezone.now", lambda: instant)

    first = reserve_budget(intent, run)
    second = reserve_budget(intent, run)

    assert first.pk == second.pk
    day = AIUsageDay.objects.get(
        organization=organization,
        usage_date=instant.astimezone(UTC).date(),
    )
    assert day.reserved_usd == intent.reserved_cost_usd
    assert AIUsageAttempt.objects.filter(run=run).count() == 1


@pytest.mark.django_db
def test_adversarial_sequential_reservations_cannot_cross_daily_ceiling():
    organization, intent, run = _context(budget="0.01", max_output=2600)
    first = reserve_budget(intent, run)
    second_job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"organization_id": str(organization.id), "text": "other"},
        idempotency_key="second-budget-job",
    )
    second_intent = create_execution_intent(
        job=second_job,
        decision=route_ai_work(job_type=second_job.type, snapshot=second_job.input_snapshot),
    )
    with ai_audit_writes():
        second_run = AIRun.objects.create(
            organization=organization,
            job=second_job,
            job_attempt=1,
            prompt_version=run.prompt_version,
            provider=second_intent.provider,
            model=second_intent.model,
            input_snapshot=second_job.input_snapshot,
            status=AIRun.Status.RUNNING,
            started_at=timezone.now(),
        )

    with pytest.raises(BudgetExceeded):
        reserve_budget(second_intent, second_run)

    day = AIUsageDay.objects.get(organization=organization)
    assert day.reserved_usd == first.reserved_usd
    assert day.reserved_usd + day.actual_usd <= Decimal("0.01")


@pytest.mark.django_db
def test_reconcile_success_failure_and_precall_cancel_are_once_only():
    organization, intent, run = _context()
    success = reserve_budget(intent, run)
    reconcile_usage(
        success,
        {"input_tokens": 100, "output_tokens": 20, "cache_hit_tokens": 5, "cost_usd": "0.0012"},
        AIUsageAttempt.Status.SUCCEEDED,
    )
    reconcile_usage(success, {"cost_usd": "9.99"}, AIUsageAttempt.Status.SUCCEEDED)
    success.refresh_from_db()
    day = AIUsageDay.objects.get(organization=organization)
    assert success.actual_usd == Decimal("0.001200")
    assert day.reserved_usd == 0
    assert day.actual_usd == Decimal("0.001200")

    for suffix, status, expected in (
        ("failed", AIUsageAttempt.Status.FAILED, intent.reserved_cost_usd),
        ("canceled", AIUsageAttempt.Status.CANCELED, Decimal("0")),
    ):
        job = JobService.create(
            organization=organization,
            job_type=Job.Type.CONTENT_GENERATE,
            input_snapshot={"organization_id": str(organization.id), "text": suffix},
            idempotency_key=suffix,
        )
        other_intent = create_execution_intent(
            job=job, decision=route_ai_work(job_type=job.type, snapshot=job.input_snapshot)
        )
        with ai_audit_writes():
            other_run = AIRun.objects.create(
                organization=organization, job=job, job_attempt=1,
                prompt_version=run.prompt_version, provider=other_intent.provider,
                model=other_intent.model, input_snapshot=job.input_snapshot,
                status=AIRun.Status.RUNNING, started_at=timezone.now(),
            )
        attempt = reserve_budget(other_intent, other_run)
        reconcile_usage(attempt, {}, status)
        attempt.refresh_from_db()
        assert attempt.actual_usd == (
            other_intent.reserved_cost_usd if status == AIUsageAttempt.Status.FAILED else expected
        )


@pytest.mark.django_db
def test_negative_usage_and_database_negative_ledgers_are_rejected():
    organization, intent, run = _context()
    attempt = reserve_budget(intent, run)
    with pytest.raises(ValueError):
        reconcile_usage(attempt, {"cost_usd": "-0.01"}, AIUsageAttempt.Status.SUCCEEDED)
    with pytest.raises(IntegrityError):
        AIUsageDay.objects.create(
            organization=organization,
            usage_date=datetime.now(UTC).date(),
            reserved_usd=Decimal("-1"),
        )
