from types import SimpleNamespace

import pytest
from django.db import connection

from apps.growth.agent.acquisition import run_proactive_acquisition
from apps.growth.agent.content_tools import run_content_strategy_agent
from apps.growth.lead_judgment import judge_candidate_for_tenant
from apps.growth.models import AgentRun, DiscoveryCandidate, OutreachDraft
from apps.identity.models import Organization
from apps.identity.models import Membership, Role
from apps.knowledge.agent_context import AgentContextPurpose, load_agent_context
from apps.knowledge.context_builder import build_mission_context
from apps.knowledge.tests.test_agent_context import _verified_page
from apps.knowledge.tests.test_knowledge_context_snapshot import (
    bind_public_evidence,
    make_context_sources,
    make_fact,
)


def _mission_sources():
    organization = Organization.objects.create(name="Mission seller", slug="mission-seller")
    other = Organization.objects.create(name="Other", slug="mission-other")
    organization, _, actor, product, mission, profile, _ = make_context_sources(
        (organization, other)
    )
    fact = make_fact(
        profile,
        actor,
        key="precision",
        value={"text": "Documented precision manufacturing"},
    )
    bind_public_evidence(fact, actor)
    page = _verified_page(organization, actor, product)
    return organization, actor, mission, fact, page


@pytest.mark.django_db
def test_mission_acquisition_freezes_one_snapshot_for_judgment_and_outreach():
    organization, _, mission, fact, page = _mission_sources()
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Target Mining",
        country="DE",
        website="",
        industry="Industrial equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "manufacturer", "types": ["manufacturer"]},
        record_hash="mission-context-candidate",
    )

    result = run_proactive_acquisition(
        organization=organization,
        candidate_id=str(candidate.id),
        mission_id=str(mission.id),
    )

    assert result.status == "waiting_approval"
    run = AgentRun.objects.get(organization=organization, agent_type="proactive")
    draft = OutreachDraft.objects.get(organization=organization)
    assert run.knowledge_context_snapshot_id is not None
    assert draft.knowledge_context_snapshot_id == run.knowledge_context_snapshot_id
    assert str(fact.id) in draft.chinese_explanation
    assert page.primary_cta_url in draft.english_draft


@pytest.mark.django_db(transaction=True)
def test_grounded_judgment_separates_seller_and_target_outside_atomic(monkeypatch):
    organization, _, mission, _, _ = _mission_sources()
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Target OEM",
        country="DE",
        website="https://target.example.test",
        industry="Industrial equipment",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "manufacturer"},
        record_hash="grounded-judgment-candidate",
    )
    snapshot = build_mission_context(organization=organization, mission=mission)
    context = load_agent_context(
        organization=organization,
        mission=mission,
        snapshot_id=snapshot.id,
    ).for_purpose(AgentContextPurpose.LEAD_JUDGMENT)
    captured = {}

    class Provider:
        def generate(self, *, prompt, schema):
            assert connection.in_atomic_block is False
            captured["prompt"] = prompt
            return {
                "industry": "Industrial equipment",
                "uses_gears": True,
                "intent": "qualified",
                "score": 80,
                "grade": "A",
                "reason": "Product and ICP fit with public target evidence.",
            }

    monkeypatch.setattr(
        "apps.growth.lead_judgment.resolve_product_ai",
        lambda organization: SimpleNamespace(
            real_requests_enabled=True,
            provider_code="fake",
            model="fake-v1",
            provider=Provider(),
        ),
    )

    output = judge_candidate_for_tenant(
        candidate.id,
        organization_id=organization.id,
        agent_context=context,
    )

    assert output["score"] == 80
    assert '"seller_context"' in captured["prompt"]
    assert '"target_company_evidence"' in captured["prompt"]
    assert captured["prompt"].index('"seller_context"') < captured["prompt"].index(
        '"target_company_evidence"'
    )


@pytest.mark.django_db
def test_mission_content_strategy_derives_brief_from_same_snapshot(monkeypatch):
    from apps.campaigns.models import ContentBrief
    from apps.platforms.models import Platform

    organization, actor, mission, _, page = _mission_sources()
    Membership.objects.create(
        user=actor,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    mission.allowed_channels = ["LINKEDIN"]
    mission.save(update_fields=["allowed_channels", "updated_at"])

    first = run_content_strategy_agent(
        organization=organization,
        creator_id=str(actor.id),
        mission_id=str(mission.id),
    )
    from apps.knowledge.models import CompanyKnowledgeProfile

    late_fact = make_fact(
        CompanyKnowledgeProfile.objects.get(organization=organization),
        actor,
        key="late_change",
        value={"text": "Changed after the AgentRun was frozen"},
    )
    bind_public_evidence(late_fact, actor)
    result = run_content_strategy_agent(
        organization=organization,
        creator_id=str(actor.id),
        mission_id=str(mission.id),
        approvals={first.pending_approval.approval_token},
    )

    assert result.status == "completed", result.terminal_reason
    run = AgentRun.objects.get(organization=organization, agent_type="content_strategy")
    brief = ContentBrief.objects.get(organization=organization)
    assert brief.knowledge_context_snapshot_id == run.knowledge_context_snapshot_id
    assert brief.target_country == "DE"
    assert brief.customer_type == "OEM"
    assert brief.content_objective == mission.objective
    assert brief.language == "en"
    assert brief.cta == page.primary_cta_label
    assert brief.landing_page_url == page.primary_cta_url
    assert brief.prohibited_claims == ["Do not claim unverified certifications"]
    assert brief.selling_points == ["Documented precision manufacturing"]
    assert list(brief.product_links.values_list("product_id", flat=True)) == [
        mission.primary_product_id
    ]
    from apps.campaigns.services import (
        build_content_generation_input,
        mark_content_brief_ready,
    )

    ready = mark_content_brief_ready(brief.id, reviewer=actor)
    generation_input = build_content_generation_input(ready.id).to_dict()
    assert generation_input["knowledge_provenance"] == {
        "knowledge_context_snapshot_id": str(run.knowledge_context_snapshot_id),
        "payload_hash": run.knowledge_context_snapshot.payload_hash,
        "schema_version": run.knowledge_context_snapshot.schema_version,
        "builder_version": run.knowledge_context_snapshot.builder_version,
    }
    assert generation_input["agent_context"]["purpose"] == "MASTER_CONTENT"
    assert "internal_context" not in generation_input["agent_context"]["seller"]
    assert generation_input["agent_context"]["seller"]["public_claims"][0][
        "fact_id"
    ]
    from copy import deepcopy

    from apps.ai.orchestration import GenerationPreflightError, _validate_generation_input

    tampered = deepcopy(generation_input)
    tampered["knowledge_provenance"]["payload_hash"] = "0" * 64
    with pytest.raises(GenerationPreflightError, match="knowledge context"):
        _validate_generation_input(tampered, organization_id=organization.id)

    from django.utils import timezone

    from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
    from apps.ai.services import PromptVersionService
    from apps.content.services import (
        ContentStateError,
        create_generated_master,
        create_platform_content,
    )
    from apps.jobs.models import Job
    from apps.jobs.services import JobService

    job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot=generation_input,
        created_by=actor,
    )
    claimed = JobService.claim(worker_id="knowledge-context-test", job_id=job.id)
    prompt = PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="knowledge-context-test",
        provider="fake",
        model="fake-v1",
        template="test",
        output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )
    with ai_audit_writes():
        ai_run = AIRun.objects.create(
            organization=organization,
            job=job,
            job_attempt=job.attempt,
            prompt_version=prompt,
            provider="fake",
            model="fake-v1",
            input_snapshot=generation_input,
            status=AIRun.Status.SUCCEEDED,
            output_json={
                "title": "Generated",
                "body": "Evidence-backed body",
                "cta": page.primary_cta_label,
                "concept_codes": [],
            },
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )
    with pytest.raises(ContentStateError, match="version 2"):
        create_generated_master(
            brief=ready,
            job=claimed,
            ai_run=ai_run,
            actor=actor,
            auto_approve=True,
        )
    public_fact_id = generation_input["agent_context"]["seller"]["public_claims"][0][
        "fact_id"
    ]
    with ai_audit_writes():
        ai_run.output_json = {
            "schema_version": 2,
            "language": "en",
            "title": "Generated",
            "body": "Evidence-backed master body",
            "cta": page.primary_cta_label,
            "landing_page_url": page.primary_cta_url,
            "concept_codes": [],
            "evidence_fact_ids": [public_fact_id],
            "platform_variants": [
                {
                    "platform_code": "LINKEDIN",
                    "language": "en",
                    "title": "LinkedIn title",
                    "body": "Evidence-backed LinkedIn adaptation",
                    "cta": page.primary_cta_label,
                    "landing_page_url": page.primary_cta_url,
                    "hashtags": ["#precision"],
                    "evidence_fact_ids": [public_fact_id],
                }
            ],
        }
        ai_run.save(update_fields=["output_json"])
    master = create_generated_master(
        brief=ready,
        job=claimed,
        ai_run=ai_run,
        actor=actor,
        auto_approve=True,
    )
    JobService.succeed(
        job.id,
        claim_token=claimed.claim_token,
        result_reference={"type": "master_content", "id": str(master.id), "version": 1},
    )
    monkeypatch.setattr(
        "apps.knowledge.context_builder.build_mission_context",
        lambda **kwargs: pytest.fail("platform generation rebuilt the snapshot"),
    )
    platform = Platform.objects.get(code="LINKEDIN")
    variant = create_platform_content(master, platform=platform, actor=actor)

    assert master.knowledge_context_snapshot_id == brief.knowledge_context_snapshot_id
    assert variant.knowledge_context_snapshot_id == master.knowledge_context_snapshot_id
    assert master.provenance["knowledge_context"] == generation_input[
        "knowledge_provenance"
    ]
    assert variant.provenance["knowledge_context"] == master.provenance[
        "knowledge_context"
    ]
    from apps.content.tasks import _platform_variant_job_input

    child_input = _platform_variant_job_input(master, actor)
    assert child_input["knowledge_provenance"] == master.provenance[
        "knowledge_context"
    ]
    assert child_input["agent_context"]["purpose"] == "PLATFORM_VARIANT"
    assert "internal_context" not in child_input["agent_context"]["seller"]
    from apps.growth.agent.content_creation_tools import run_platform_variants_agent

    first_variant_run = run_platform_variants_agent(
        organization=organization,
        master_id=str(master.id),
        actor_id=str(actor.id),
    )
    final_variant_run = run_platform_variants_agent(
        organization=organization,
        master_id=str(master.id),
        actor_id=str(actor.id),
        approvals={first_variant_run.pending_approval.approval_token},
    )
    assert final_variant_run.status == "completed"
    variant_agent_run = AgentRun.objects.get(
        organization=organization,
        agent_type="platform_variants",
    )
    assert variant_agent_run.knowledge_context_snapshot_id == master.knowledge_context_snapshot_id
