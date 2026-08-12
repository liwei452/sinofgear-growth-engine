from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.ai.models import AIExecutionIntent, AIProviderConfiguration
from apps.ai.routing import create_execution_intent, route_ai_work
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService


def _connected(organization, **limits):
    defaults = {
        "connection_state": AIProviderConfiguration.ConnectionState.CONNECTED,
        "key_suffix": "safe",
        **limits,
    }
    return AIProviderConfiguration.objects.create(organization=organization, **defaults)


@pytest.mark.django_db
def test_routine_content_uses_stable_flash_policy():
    organization = Organization.objects.create(name="Routing", slug="routing")
    _connected(organization)

    decision = route_ai_work(
        job_type=Job.Type.CONTENT_GENERATE,
        snapshot={"organization_id": str(organization.id), "body": "routine"},
    )

    assert decision.provider == "deepseek"
    assert decision.model == "deepseek-v4-flash"
    assert decision.thinking_enabled is False
    assert (decision.policy_code, decision.policy_version) == ("deepseek-routing-v1", 1)
    assert isinstance(decision.reserved_cost_usd, Decimal)


@pytest.mark.django_db
def test_conflicting_lead_evidence_uses_pro_and_retry_reuses_frozen_intent():
    organization = Organization.objects.create(name="Lead Route", slug="lead-route")
    _connected(organization)
    snapshot = {
        "organization_id": str(organization.id),
        "conflicting_evidence": True,
        "evidence": [{"original_text": "need gears"}],
    }
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=snapshot,
        idempotency_key="route-retry",
    )
    decision = route_ai_work(job_type=job.type, snapshot=snapshot)
    first = create_execution_intent(job=job, decision=decision)

    same = create_execution_intent(
        job=job,
        decision=route_ai_work(job_type=job.type, snapshot=snapshot),
    )

    assert first.pk == same.pk
    assert first.model == "deepseek-v4-pro"
    assert first.thinking_enabled is True
    with pytest.raises(ValidationError):
        AIExecutionIntent.objects.filter(pk=first.pk).update(model="injected")


@pytest.mark.django_db
def test_override_requires_credentials_manage_and_model_is_not_a_routing_input():
    organization = Organization.objects.create(name="Override", slug="override")
    _connected(organization)
    snapshot = {
        "organization_id": str(organization.id),
        "model": "attacker-model",
        "provider": "attacker-provider",
    }

    with pytest.raises(PermissionDenied):
        route_ai_work(
            job_type=Job.Type.CONTENT_GENERATE,
            snapshot=snapshot,
            administrator_override=True,
        )

    user = get_user_model().objects.create_user(username="routing-admin")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_administrator(),
    )
    decision = route_ai_work(
        job_type=Job.Type.CONTENT_GENERATE,
        snapshot=snapshot,
        administrator_override=True,
        actor=user,
    )
    assert decision.model == "deepseek-v4-pro"
    assert decision.override_reason == "administrator_enhanced_analysis"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [
        AIProviderConfiguration.ConnectionState.NOT_CONFIGURED,
        AIProviderConfiguration.ConnectionState.NEEDS_RECONNECT,
        AIProviderConfiguration.ConnectionState.CONFIGURING,
    ],
)
def test_routing_fails_closed_unless_configuration_is_stably_connected(state):
    organization = Organization.objects.create(name=state, slug=state.lower().replace("_", "-"))
    values = {"connection_state": state}
    if state == AIProviderConfiguration.ConnectionState.CONFIGURING:
        from django.utils import timezone
        import uuid

        values.update(operation_token=uuid.uuid4(), operation_started_at=timezone.now())
    AIProviderConfiguration.objects.create(organization=organization, **values)

    with pytest.raises(ValidationError, match="deepseek_not_connected"):
        route_ai_work(
            job_type=Job.Type.CONTENT_GENERATE,
            snapshot={"organization_id": str(organization.id)},
        )
