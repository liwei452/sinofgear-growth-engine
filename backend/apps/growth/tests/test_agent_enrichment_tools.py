from types import SimpleNamespace

import pytest

from apps.growth.agent.acquisition import build_proactive_acquisition_tools
from apps.growth.agent.memory import Memory
from apps.growth.agent.planner import DeterministicPlanner, Plan
from apps.growth.agent.runtime import AgentRuntime
from apps.growth.agent.tools import ToolRegistry
from apps.growth.models import (
    CandidateEnrichmentSnapshot,
    DiscoveryCandidate,
    FollowUp,
    GoogleMapsDiscoveryConfig,
    TargetAccount,
)
from apps.identity.models import Organization
from integrations.secrets import encrypt_secret
from integrations.sources.google_places import MapsBatch, MapsPlace


class FakeWebsiteTransport:
    def __init__(self, pages):
        self.pages = pages

    def fetch_html(self, url, *, timeout_seconds, max_bytes):
        return self.pages[url]


class FakeMapsSource:
    def __init__(self, batch):
        self.batch = batch

    def fetch(self, query):
        return self.batch


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Enrichment agent", slug="enrichment-agent")


def _candidate(organization, website):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="ABC Gearbox Repair",
        country="Vietnam",
        website=website,
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
        record_hash=f"enrich-tool-{website or 'none'}",
    )


def test_website_enrich_tool_reads_public_facts_and_contacts(organization):
    candidate = _candidate(organization, "https://abc.example")
    transport = FakeWebsiteTransport(
        {
            "https://abc.example": (
                "<title>ABC Gearbox Repair</title>"
                "<p>industrial gearbox repair and helical gears</p>"
                "<p>sales@abc.example</p>"
            )
        }
    )
    tools = ToolRegistry(
        build_proactive_acquisition_tools(organization, website_transport=transport)
    )
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="read website",
                tool_name="website_enrich_candidate",
                tool_args={"candidate_id": str(candidate.id)},
            ),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="enrich", memory=Memory())

    assert result.status == "completed"
    output = result.steps[0].output
    assert output["mode"] == "WEBSITE_PUBLIC"
    assert any(path.get("url") == "mailto:sales@abc.example" for path in output["public_contact_paths"])


def test_website_enrich_tool_skips_candidate_without_website(organization):
    candidate = _candidate(organization, "")
    tools = ToolRegistry(build_proactive_acquisition_tools(organization))
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="read website",
                tool_name="website_enrich_candidate",
                tool_args={"candidate_id": str(candidate.id)},
            ),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="enrich", memory=Memory())

    assert result.status == "completed"
    assert result.steps[0].output == {"skipped": True, "reason": "no_website"}


def test_verify_contacts_tool_verifies_snapshot_emails(organization, monkeypatch):
    candidate = _candidate(organization, "")
    CandidateEnrichmentSnapshot.objects.create(
        organization=organization,
        candidate=candidate,
        mode="WEBSITE_PUBLIC",
        facts=[],
        public_contact_paths=[
            {"label": "sales@abc.example", "url": "mailto:sales@abc.example"},
        ],
        uncertainties=[],
        evidence_envelope={},
    )
    monkeypatch.setattr(
        "apps.growth.agent.acquisition.verify_email",
        lambda email: {"email": email, "status": "DOMAIN_RESOLVES"},
    )
    tools = ToolRegistry(build_proactive_acquisition_tools(organization))
    planner = DeterministicPlanner(
        [
            Plan(
                reasoning="verify",
                tool_name="verify_candidate_contacts",
                tool_args={"candidate_id": str(candidate.id)},
            ),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="verify", memory=Memory())

    assert result.status == "completed"
    assert result.steps[0].output["emails"] == ["sales@abc.example"]
    assert result.steps[0].output["verifications"][0]["status"] == "DOMAIN_RESOLVES"


def test_discover_maps_tool_creates_candidates(organization):
    GoogleMapsDiscoveryConfig.objects.create(
        organization=organization,
        enabled=True,
        api_key_ciphertext=encrypt_secret("test-key"),
        cities=[{"name": "Hanoi", "country_code": "VN"}],
        keywords=["gearbox"],
        daily_quota=1,
    )
    batch = MapsBatch(
        places=(
            MapsPlace(
                place_id="p1",
                name="PT Gearbox",
                address="Hanoi",
                website="https://ptgear.example",
                phone="+84",
                primary_type="industrial_supplier",
                types=("industrial_supplier", "gearbox_repair_shop"),
                country_code="VN",
                source_url="https://maps.example/p1",
            ),
        ),
        capability_snapshot={},
        total_count=1,
    )
    tools = ToolRegistry(
        build_proactive_acquisition_tools(
            organization,
            maps_source_factory=lambda api_key: FakeMapsSource(batch),
        )
    )
    planner = DeterministicPlanner(
        [
            Plan(reasoning="discover", tool_name="discover_maps_candidates", tool_args={}),
            Plan(reasoning="done", terminal_reason="complete"),
        ]
    )
    runtime = AgentRuntime(planner=planner, tools=tools)
    result = runtime.run(goal="discover", memory=Memory())

    assert result.status == "completed"
    assert result.steps[0].output["created_count"] == 1
    assert DiscoveryCandidate.objects.filter(
        organization=organization,
        company_name="PT Gearbox",
    ).count() == 1


def test_proactive_acquisition_website_path_end_to_end(organization, monkeypatch):
    from apps.growth.agent.acquisition import run_proactive_acquisition

    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="ABC Gearbox Repair",
        country="Vietnam",
        website="https://abc.example",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["gearbox_repair_shop"]},
        record_hash="website-path-hash",
        is_demo=False,
    )
    transport = FakeWebsiteTransport(
        {
            "https://abc.example": (
                "<title>ABC Gearbox Repair</title>"
                "<p>industrial gearbox repair and helical gears</p>"
                "<p>sales@abc.example</p>"
            )
        }
    )
    monkeypatch.setattr(
        "apps.growth.agent.acquisition.verify_email",
        lambda email: {"email": email, "status": "DOMAIN_RESOLVES"},
    )

    first = run_proactive_acquisition(
        organization=organization,
        candidate_id=str(candidate.id),
        website_transport=transport,
    )
    assert first.status == "waiting_approval"
    token = first.pending_approval.approval_token

    resumed = run_proactive_acquisition(
        organization=organization,
        candidate_id=str(candidate.id),
        website_transport=transport,
        approvals={token},
    )
    assert resumed.status == "completed"
    snapshot = CandidateEnrichmentSnapshot.objects.get(candidate=candidate)
    assert snapshot.mode == "WEBSITE_PUBLIC"
    account = TargetAccount.objects.get(
        organization=organization,
        source_identity=f"candidate:{candidate.id}",
    )
    follow_up = FollowUp.objects.get(organization=organization, account=account)
    assert follow_up.stage == "EMAIL_1_SENT"


def test_acquisition_write_tools_are_classified_write_but_only_send_needs_approval(organization):
    tools = ToolRegistry(build_proactive_acquisition_tools(organization))

    risks = {tool.name: tool.risk for tool in tools._tools.values()}
    approvals = {tool.name: tool.requires_approval for tool in tools._tools.values()}

    assert risks["discover_maps_candidates"] == "write"
    assert risks["enrich_candidate"] == "write"
    assert risks["website_enrich_candidate"] == "write"
    assert risks["add_to_follow_up"] == "write"
    assert risks["draft_outreach"] == "write"
    assert risks["send_email"] == "write"

    assert approvals["enrich_candidate"] is False
    assert approvals["add_to_follow_up"] is False
    assert approvals["draft_outreach"] is False
    assert approvals["send_email"] is True


def test_send_email_tool_respects_outreach_cooldown(organization, monkeypatch):
    from apps.growth.agent import acquisition as acq

    candidate = SimpleNamespace(id="candidate-cooldown")
    draft = SimpleNamespace(id="draft-1", english_draft="Draft")
    account = SimpleNamespace(
        id="account-cooldown",
        outreach_drafts=SimpleNamespace(order_by=lambda *a, **k: SimpleNamespace(first=lambda: draft)),
        outreach_messages=SimpleNamespace(filter=lambda **k: SimpleNamespace(exists=lambda: True)),
    )
    monkeypatch.setattr(acq, "_candidate", lambda org, args: candidate)
    monkeypatch.setattr(acq, "_account_for_candidate", lambda org, candidate: account)
    calls = []
    monkeypatch.setattr(acq, "record_sent", lambda **kwargs: calls.append(kwargs) or SimpleNamespace())

    tools = ToolRegistry(acq.build_proactive_acquisition_tools(organization))
    result = tools.get("send_email").func({"candidate_id": "candidate-cooldown"})

    assert result.ok is False
    assert "cooldown" in result.error
    assert calls == []


def test_send_email_tool_uses_contact_email_not_placeholder(organization, monkeypatch):
    from apps.growth.agent import acquisition as acq

    candidate = SimpleNamespace(id="candidate-email")
    draft = SimpleNamespace(id="draft-1", english_draft="Draft")
    account = SimpleNamespace(
        id="account-email",
        outreach_drafts=SimpleNamespace(order_by=lambda *a, **k: SimpleNamespace(first=lambda: draft)),
        outreach_messages=SimpleNamespace(filter=lambda **k: SimpleNamespace(exists=lambda: False)),
    )
    monkeypatch.setattr(acq, "_candidate", lambda org, args: candidate)
    monkeypatch.setattr(acq, "_account_for_candidate", lambda org, candidate: account)
    monkeypatch.setattr(acq, "_contact_email_for_candidate", lambda candidate: "buyer@example.com")
    calls = []
    monkeypatch.setattr(
        acq,
        "record_sent",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(provider_message_id="m1", provider="mock", status="SENT"),
    )

    tools = ToolRegistry(acq.build_proactive_acquisition_tools(organization))
    result = tools.get("send_email").func({"candidate_id": "candidate-email"})

    assert result.ok is True
    assert calls[0]["email"] == "buyer@example.com"


def test_send_email_tool_fails_without_contact_email(organization, monkeypatch):
    from apps.growth.agent import acquisition as acq

    candidate = SimpleNamespace(id="candidate-no-email")
    draft = SimpleNamespace(id="draft-1", english_draft="Draft")
    account = SimpleNamespace(
        id="account-no-email",
        outreach_drafts=SimpleNamespace(order_by=lambda *a, **k: SimpleNamespace(first=lambda: draft)),
        outreach_messages=SimpleNamespace(filter=lambda **k: SimpleNamespace(exists=lambda: False)),
    )
    monkeypatch.setattr(acq, "_candidate", lambda org, args: candidate)
    monkeypatch.setattr(acq, "_account_for_candidate", lambda org, candidate: account)
    monkeypatch.setattr(acq, "_contact_email_for_candidate", lambda candidate: None)
    calls = []
    monkeypatch.setattr(acq, "record_sent", lambda **kwargs: calls.append(kwargs))

    tools = ToolRegistry(acq.build_proactive_acquisition_tools(organization))
    result = tools.get("send_email").func({"candidate_id": "candidate-no-email"})

    assert result.ok is False
    assert "contact email" in result.error
    assert calls == []
