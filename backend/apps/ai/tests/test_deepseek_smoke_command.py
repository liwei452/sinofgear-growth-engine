from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.ai.models import (
    AIProviderCall,
    AIProviderConfiguration,
    AIRun,
    AIUsageAttempt,
)
from apps.identity.models import Organization
from integrations.ai.providers import ProviderResult, ProviderUnavailableError


class FakeStore:
    def read(self, target):
        return "test-credential-placeholder"


class FakeProvider:
    calls = []
    error = None

    def __init__(self, *, credential_store, **kwargs):
        self.credential_store = credential_store

    def generate(self, *, prompt, schema, execution):
        type(self).calls.append((prompt, schema, execution))
        if type(self).error is not None:
            raise type(self).error
        output = (
            {"title": "Gear test", "body": "Schema-bound smoke output."}
            if "title" in schema.get("properties", {})
            else {"connected": True}
        )
        return ProviderResult(
            output=output,
            metadata={
                "model": "deepseek-v4-flash",
                "thinking_enabled": False,
                "input_tokens": 5,
                "output_tokens": 2,
                "cache_hit_tokens": 1,
                "duration_ms": 12,
                "request_id": "safe-request-id",
            },
        )


@pytest.fixture(autouse=True)
def smoke_dependencies(monkeypatch):
    FakeProvider.calls = []
    FakeProvider.error = None
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "apps.ai.management.commands.deepseek_smoke_test.get_credential_store",
        lambda: FakeStore(),
    )
    monkeypatch.setattr(
        "apps.ai.management.commands.deepseek_smoke_test.DeepSeekProvider",
        FakeProvider,
    )


@pytest.fixture
def configured_org(db):
    organization = Organization.objects.create(name="Smoke Org", slug="smoke-org")
    AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state=AIProviderConfiguration.ConnectionState.CONNECTED,
        key_suffix="safe",
    )
    return organization


def run_smoke(organization, **options):
    output = StringIO()
    call_command(
        "deepseek_smoke_test",
        organization_slug=organization.slug,
        acknowledge_paid_call=True,
        stdout=output,
        **options,
    )
    return output.getvalue()


def test_smoke_command_refuses_without_paid_acknowledgement(configured_org):
    with pytest.raises(CommandError, match="acknowledge-paid-call"):
        call_command(
            "deepseek_smoke_test", organization_slug=configured_org.slug
        )
    assert FakeProvider.calls == []


def test_smoke_command_requires_one_explicit_organization(db):
    Organization.objects.create(name="One", slug="one")
    Organization.objects.create(name="Two", slug="two")

    with pytest.raises(CommandError, match="organization-slug"):
        call_command("deepseek_smoke_test", acknowledge_paid_call=True)
    assert FakeProvider.calls == []


def test_smoke_command_refuses_fake_provider_mode(configured_org, settings):
    settings.PHASE_B1_SCHEMA_FAKE_ALLOWED = True

    with pytest.raises(CommandError, match="fake provider mode"):
        run_smoke(configured_org)
    assert FakeProvider.calls == []


def test_smoke_command_refuses_unsupported_credential_backend(configured_org, settings):
    settings.AI_CREDENTIAL_STORE = "memory"

    with pytest.raises(CommandError, match="Windows Credential Manager"):
        run_smoke(configured_org)
    assert FakeProvider.calls == []


def test_smoke_command_refuses_non_windows_host(configured_org, monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")

    with pytest.raises(CommandError, match="Windows Credential Manager"):
        run_smoke(configured_org)
    assert FakeProvider.calls == []


def test_smoke_command_refuses_missing_or_unstable_configuration(db):
    missing = Organization.objects.create(name="Missing", slug="missing")
    with pytest.raises(CommandError, match="stable CONNECTED"):
        run_smoke(missing)

    unstable = Organization.objects.create(name="Unstable", slug="unstable")
    AIProviderConfiguration.objects.create(
        organization=unstable,
        connection_state=AIProviderConfiguration.ConnectionState.NEEDS_RECONNECT,
    )
    with pytest.raises(CommandError, match="stable CONNECTED"):
        run_smoke(unstable)
    assert FakeProvider.calls == []


def test_smoke_command_outputs_only_safe_admin_fields(configured_org):
    output = run_smoke(configured_org)

    assert "PASS" in output
    assert "model=deepseek-v4-flash" in output
    assert "thinking=false" in output
    assert "input_tokens=5" in output
    assert "output_tokens=2" in output
    assert "cache_hit_tokens=1" in output
    assert "estimated_cost_usd=0.000002" in output
    assert "run_id=" in output
    assert "test-credential-placeholder" not in output
    assert "safe-request-id" not in output
    assert "SinofGear/DeepSeek" not in output
    assert "key_suffix" not in output
    assert len(FakeProvider.calls) == 1
    _, _, execution = FakeProvider.calls[0]
    assert execution.model == "deepseek-v4-flash"
    assert execution.thinking_enabled is False
    run_id = next(
        field.split("=", 1)[1]
        for field in output.split()
        if field.startswith("run_id=")
    )
    run = AIRun.objects.get(pk=run_id)
    assert run.organization == configured_org
    assert run.provider == "deepseek"
    assert run.model == "deepseek-v4-flash"
    assert run.status == AIRun.Status.SUCCEEDED
    usage = AIUsageAttempt.objects.get(run=run)
    assert usage.status == AIUsageAttempt.Status.SUCCEEDED
    assert usage.input_tokens == 5
    assert usage.output_tokens == 2
    assert AIProviderCall.objects.filter(
        run=run, status=AIProviderCall.Status.SUCCEEDED
    ).count() == 1


def test_content_generation_requires_separate_opt_in(configured_org):
    run_smoke(configured_org)
    assert len(FakeProvider.calls) == 1

    FakeProvider.calls = []
    run_smoke(configured_org, include_content_generation=True)
    assert len(FakeProvider.calls) == 2


def test_provider_failure_is_reported_without_provider_detail(configured_org):
    FakeProvider.error = ProviderUnavailableError(
        "private provider response test-credential-placeholder"
    )

    with pytest.raises(CommandError, match="provider_unavailable") as caught:
        run_smoke(configured_org)
    assert "test-credential-placeholder" not in str(caught.value)
    run = AIRun.objects.get(organization=configured_org)
    assert run.status == AIRun.Status.FAILED
    assert run.error == {"code": "provider_unavailable"}

    pending = [caught.value]
    seen = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        assert "test-credential-placeholder" not in repr(value)
        if isinstance(value, BaseException):
            pending.extend(item for item in (value.__cause__, value.__context__) if item)
            traceback = value.__traceback__
            while traceback is not None:
                for local_value in traceback.tb_frame.f_locals.values():
                    assert "test-credential-placeholder" not in repr(local_value)
                traceback = traceback.tb_next


def test_zero_budget_refuses_before_provider_call(configured_org):
    AIProviderConfiguration.objects.filter(organization=configured_org).update(
        daily_budget_usd=0
    )

    with pytest.raises(CommandError, match="deepseek_daily_budget_exceeded"):
        run_smoke(configured_org)

    assert FakeProvider.calls == []
    run = AIRun.objects.get(organization=configured_org)
    assert run.status == AIRun.Status.FAILED
    assert run.error == {"code": "deepseek_daily_budget_exceeded"}
    assert not AIProviderCall.objects.filter(run=run).exists()
