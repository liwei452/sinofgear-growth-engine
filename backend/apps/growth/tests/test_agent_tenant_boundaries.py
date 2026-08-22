from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.db import connection

from apps.ai.provider_config import ProductAIRuntime
from apps.growth.agent.acquisition import (
    build_proactive_acquisition_tools,
    resume_proactive_acquisition,
)
from apps.growth.agent.tools import ToolRegistry
from apps.growth.models import AgentRun, DiscoveryCandidate, GoogleMapsDiscoveryConfig
from apps.identity.models import Organization
from integrations.secrets import encrypt_secret
from integrations.sources.google_places import MapsBatch


@pytest.fixture
def organizations(db):
    return (
        Organization.objects.create(name="Agent tenant A", slug=f"agent-a-{uuid4()}"),
        Organization.objects.create(name="Agent tenant B", slug=f"agent-b-{uuid4()}"),
    )


def _candidate(organization, *, website=""):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Tenant Candidate",
        country="US",
        website=website,
        industry="industrial supplier",
        status=DiscoveryCandidate.Status.ACCEPTED,
        raw_record={"primary_type": "industrial_supplier", "types": []},
        record_hash=f"tenant-boundary-{uuid4()}",
    )


@pytest.mark.django_db(transaction=True)
def test_judge_tool_resolves_tenant_ai_config_before_network(organizations, monkeypatch):
    from apps.growth import lead_judgment

    organization, _other = organizations
    candidate = _candidate(organization)

    class Provider:
        def generate(self, *, prompt, schema):
            assert connection.in_atomic_block is False
            return {
                "industry": "industrial supplier",
                "uses_gears": True,
                "intent": "buyer",
                "score": 80,
                "grade": "A",
                "reason": "verified fit",
            }

    def resolve(loaded_organization):
        assert connection.in_atomic_block is True
        assert loaded_organization.id == organization.id
        return ProductAIRuntime(
            mode="CONFIGURED_AI",
            provider_label="Test provider",
            provider_code="deepseek",
            model="deepseek-chat",
            configured=True,
            real_requests_enabled=True,
            provider=Provider(),
        )

    monkeypatch.setattr(lead_judgment, "resolve_product_ai", resolve)
    tools = ToolRegistry(build_proactive_acquisition_tools(organization))

    result = tools.get("judge_candidate").func(
        {"candidate_id": str(candidate.id), "organization_id": str(uuid4())}
    )

    assert result.ok is True
    assert result.output["grade"] == "A"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("boundary", ["maps", "website"])
def test_network_tools_prepare_with_trusted_tenant_and_call_outside_transaction(
    organizations, monkeypatch, boundary
):
    from apps.growth.agent import acquisition

    organization, _other = organizations
    if boundary == "maps":
        GoogleMapsDiscoveryConfig.objects.create(
            organization=organization,
            enabled=True,
            api_key_ciphertext=encrypt_secret("test-key"),
            cities=[{"name": "Austin", "country_code": "US"}],
            keywords=["gear"],
            daily_quota=1,
        )

        class Source:
            def fetch(self, query):
                assert connection.in_atomic_block is False
                return MapsBatch(places=(), capability_snapshot={}, total_count=0)

        real_run = acquisition.run_maps_discovery

        def run_with_tenant(*args, **kwargs):
            assert kwargs["organization_id"] == organization.id
            return real_run(*args, **kwargs)

        monkeypatch.setattr(acquisition, "run_maps_discovery", run_with_tenant)
        tools = ToolRegistry(
            build_proactive_acquisition_tools(
                organization,
                maps_source_factory=lambda api_key: Source(),
            )
        )
        result = tools.get("discover_maps_candidates").func({})
    else:
        candidate = _candidate(organization, website="https://tenant.example")

        class Transport:
            def fetch_html(self, url, *, timeout_seconds, max_bytes):
                assert connection.in_atomic_block is False
                return "<title>Tenant</title><p>industrial gear supplier</p>"

        def resolve(loaded_organization):
            assert connection.in_atomic_block is True
            return ProductAIRuntime(
                mode="FAKE_OFFLINE",
                provider_label="Offline",
                provider_code="fake",
                model="fake",
                configured=False,
                real_requests_enabled=False,
                provider=SimpleNamespace(),
            )

        monkeypatch.setattr(
            "apps.growth.lead_judgment.resolve_product_ai",
            resolve,
        )
        tools = ToolRegistry(
            build_proactive_acquisition_tools(
                organization,
                website_transport=Transport(),
            )
        )
        result = tools.get("website_enrich_candidate").func(
            {"candidate_id": str(candidate.id)}
        )

    assert result.ok is True


@pytest.mark.django_db(transaction=True)
def test_orm_tool_rejects_cross_tenant_candidate_and_uses_short_transaction(
    organizations, monkeypatch
):
    from apps.growth.agent import acquisition

    organization, other = organizations
    own = _candidate(organization)
    foreign = _candidate(other)
    real_prepare = acquisition.prepare_candidate_enrichment

    def prepare_in_tenant(*, candidate, organization_id):
        assert connection.in_atomic_block is True
        assert candidate.organization_id == organization.id
        assert organization_id == organization.id
        return real_prepare(candidate=candidate, organization_id=organization_id)

    monkeypatch.setattr(acquisition, "prepare_candidate_enrichment", prepare_in_tenant)
    tool = ToolRegistry(build_proactive_acquisition_tools(organization)).get(
        "enrich_candidate"
    )

    assert tool.func({"candidate_id": str(own.id)}).ok is True
    foreign_result = tool.func({"candidate_id": str(foreign.id)})
    assert foreign_result.ok is False
    assert "not found" in foreign_result.error


@pytest.mark.django_db(transaction=True)
def test_resume_uses_trusted_organization_for_queries_and_continue(
    organizations, monkeypatch
):
    from apps.growth.agent import acquisition

    organization, _other = organizations
    candidate = _candidate(organization)
    run = AgentRun.objects.create(
        organization=organization,
        idempotency_key=f"proactive:{candidate.id}",
        goal="resume",
        agent_type="proactive",
        status=AgentRun.Status.WAITING_APPROVAL,
        max_steps=20,
    )
    captured = {}

    def resolve_run(**kwargs):
        assert connection.in_atomic_block is True
        return SimpleNamespace(planner=SimpleNamespace())

    def continue_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed")

    monkeypatch.setattr(acquisition, "resolve_run_execution", resolve_run)
    monkeypatch.setattr(acquisition, "continue_agent_run", continue_run)

    result = resume_proactive_acquisition(
        organization=organization,
        candidate_id=str(candidate.id),
        approval_token="approved",
    )

    assert result.status == "completed"
    assert captured["run"].id == run.id
    assert captured["organization_id"] == organization.id
