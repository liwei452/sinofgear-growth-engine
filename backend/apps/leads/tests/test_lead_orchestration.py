from copy import deepcopy

import pytest

from apps.ai.models import AIRun, PromptVersion
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import KnowledgeStatus
from apps.leads.models import LeadCandidate, LeadInsight
from apps.leads.orchestration import execute_lead_analysis_job
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.leads.services import build_analysis_snapshot
from integrations.ai.providers import provider_registry

from .test_analysis_snapshot import _valid_output


class SequenceProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def generate(self, *, prompt, schema):
        del prompt, schema
        output = self.outputs[self.calls]
        self.calls += 1
        return deepcopy(output)


class CancelingLeadProvider:
    def __init__(self, job_id, output):
        self.job_id = job_id
        self.output = output

    def generate(self, *, prompt, schema):
        del prompt, schema
        JobService.cancel(self.job_id)
        return deepcopy(self.output)


class ReclaimingLeadProvider:
    def __init__(self, job_id, output):
        self.job_id = job_id
        self.output = output

    def generate(self, *, prompt, schema):
        del prompt, schema
        job = Job.objects.get(pk=self.job_id)
        JobService.fail(
            job.id,
            claim_token=job.claim_token,
            error={"code": "provider_error"},
        )
        JobService.retry(job.id)
        JobService.claim(worker_id="replacement-worker", job_id=job.id)
        return deepcopy(self.output)


def _analysis_context(candidate, evidence, user):
    Membership.objects.create(
        user=user,
        organization=candidate.organization,
        role=Role.objects.create_operator(),
    )
    snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-analysis-test",
        provider="lead-sequence",
        model="fake-lead-v1",
        template="Analyze this frozen public lead input:\n{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=snapshot,
        idempotency_key=f"lead-analysis-{candidate.id}-{candidate.version}",
        created_by=user,
    )
    return snapshot, prompt, job


@pytest.mark.django_db
def test_success_persists_one_audited_insight_and_durable_result_reference(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    provider_registry.register("lead-sequence", SequenceProvider([output]), replace=True)

    run = execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    insight = LeadInsight.objects.get(ai_run=run)
    assert run.status == AIRun.Status.SUCCEEDED
    assert run.input_snapshot == job.input_snapshot == snapshot
    assert run.output_json == output
    assert candidate.status == LeadCandidate.Status.ANALYZED
    assert job.result_reference == {
        "lead_candidate_id": str(candidate.id),
        "lead_insight_id": str(insight.id),
        "ai_run_id": str(run.id),
    }


@pytest.mark.django_db
def test_invalid_output_is_regenerated_once_then_succeeds(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    valid = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    invalid = deepcopy(valid)
    invalid["reasons"][0]["evidence_ids"] = []
    provider = SequenceProvider([invalid, valid])
    provider_registry.register("lead-sequence", provider, replace=True)

    run = execute_lead_analysis_job(job.id, prompt.id)

    assert provider.calls == 2
    assert run.status == AIRun.Status.SUCCEEDED
    assert LeadInsight.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_double_invalid_output_fails_without_insight_and_restores_candidate(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    invalid = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    invalid["capability_matches"][0]["capability_code"] = "CAP_UNKNOWN"
    provider = SequenceProvider([invalid, invalid])
    provider_registry.register("lead-sequence", provider, replace=True)

    run = execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert provider.calls == 2
    assert run.status == AIRun.Status.FAILED
    assert run.error == {
        "code": "invalid_provider_output",
        "message": "Provider output did not match the required schema.",
    }
    assert job.status == Job.Status.FAILED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert LeadInsight.objects.filter(candidate=candidate).count() == 0


@pytest.mark.django_db
def test_canceled_worker_cannot_finalize_insight_and_restores_candidate(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    provider_registry.register(
        "lead-sequence", CancelingLeadProvider(job.id, output), replace=True
    )

    run = execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert run.status == AIRun.Status.CANCELED
    assert job.status == Job.Status.CANCELED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_duplicate_delivery_returns_same_result_without_appending_history(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    provider = SequenceProvider([output])
    provider_registry.register("lead-sequence", provider, replace=True)

    first = execute_lead_analysis_job(job.id, prompt.id)
    second = execute_lead_analysis_job(job.id, prompt.id)

    assert second.id == first.id
    assert provider.calls == 1
    assert LeadInsight.objects.filter(candidate=candidate).count() == 1


@pytest.mark.django_db
def test_deliberate_job_retry_creates_new_airun_and_eventual_insight(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    valid = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    invalid = deepcopy(valid)
    invalid["reasons"][0]["evidence_ids"] = []
    provider = SequenceProvider([invalid, invalid, valid])
    provider_registry.register("lead-sequence", provider, replace=True)

    first = execute_lead_analysis_job(job.id, prompt.id)
    JobService.retry(job.id)
    second = execute_lead_analysis_job(job.id, prompt.id)

    candidate.refresh_from_db()
    assert first.status == AIRun.Status.FAILED
    assert second.status == AIRun.Status.SUCCEEDED
    assert second.id != first.id
    assert second.job_attempt == 2
    assert candidate.status == LeadCandidate.Status.ANALYZED
    assert list(candidate.insights.values_list("version", flat=True)) == [1]


@pytest.mark.django_db
def test_new_analysis_job_appends_version_without_overwriting_history(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    first_snapshot, first_prompt, first_job = _analysis_context(candidate, evidence, user)
    first_output = _valid_output(snapshot=first_snapshot, evidence_id=evidence.id)
    provider_registry.register(
        "lead-sequence", SequenceProvider([first_output]), replace=True
    )
    first_run = execute_lead_analysis_job(first_job.id, first_prompt.id)

    second_snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    second_prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="lead-analysis-second",
        provider="lead-sequence-second",
        model="fake-lead-v2",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    second_job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=second_snapshot,
        idempotency_key=f"lead-analysis-second-{candidate.id}",
        created_by=user,
    )
    second_output = _valid_output(snapshot=second_snapshot, evidence_id=evidence.id)
    second_output["need_summary_en"] = "Updated audited conclusion."
    provider_registry.register(
        "lead-sequence-second", SequenceProvider([second_output]), replace=True
    )

    second_run = execute_lead_analysis_job(second_job.id, second_prompt.id)

    insights = list(candidate.insights.order_by("version"))
    assert [row.version for row in insights] == [1, 2]
    assert insights[0].ai_run_id == first_run.id
    assert insights[1].ai_run_id == second_run.id
    assert first_run.output_json["need_summary_en"] != second_run.output_json["need_summary_en"]


@pytest.mark.django_db
def test_stale_worker_cannot_finalize_or_recover_candidate(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    provider_registry.register(
        "lead-sequence", ReclaimingLeadProvider(job.id, output), replace=True
    )

    with pytest.raises(StaleJobWorkerError):
        execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    run = AIRun.objects.get(job=job, job_attempt=1)
    assert job.status == Job.Status.RUNNING
    assert job.attempt == 2
    assert job.claimed_by == "replacement-worker"
    assert run.status == AIRun.Status.RUNNING
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_execution_and_result_references_use_frozen_state_after_live_rows_change(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    approved_capability_evidence,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    source_content = evidence.source_signal.source_content
    source_content.author_public_name = "Changed after snapshot"
    source_content.save(update_fields=["author_public_name", "updated_at"])
    with _test_fixture_writes():
        for row in (
            approved_requirement,
            approved_capability,
            approved_capability_evidence,
        ):
            row.status = KnowledgeStatus.DEPRECATED
            row.version += 1
            row.save()
    provider_registry.register("lead-sequence", SequenceProvider([output]), replace=True)

    run = execute_lead_analysis_job(job.id, prompt.id)

    assert (run.status, run.error) == (AIRun.Status.SUCCEEDED, None)
    assert run.input_snapshot == snapshot
    assert LeadInsight.objects.get(ai_run=run).ontology_snapshot == snapshot[
        "ontology_snapshot"
    ]


@pytest.mark.django_db
def test_valid_repeated_capability_match_does_not_duplicate_requirement_history(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    output["capability_matches"].append(deepcopy(output["capability_matches"][0]))
    provider_registry.register("lead-sequence", SequenceProvider([output]), replace=True)

    run = execute_lead_analysis_job(job.id, prompt.id)

    insight = LeadInsight.objects.get(ai_run=run)
    assert run.status == AIRun.Status.SUCCEEDED
    assert insight.requirements.count() == 1
