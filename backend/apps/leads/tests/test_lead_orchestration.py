from copy import deepcopy

import pytest
from django.db import models
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.orchestration import GenerationPreflightError
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeConcept,
    KnowledgeConceptEvidence,
    KnowledgeEvidence,
    KnowledgeStatus,
)
from apps.leads.models import (
    LeadAnalysisBinding,
    LeadCandidate,
    LeadInsight,
    lead_history_writes,
)
from apps.leads.orchestration import execute_lead_analysis_job
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.leads.services import LeadService, LeadStateError, build_analysis_snapshot
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
    with lead_history_writes():
        LeadAnalysisBinding.objects.create(
            organization=candidate.organization,
            job=job,
            candidate=candidate,
            prompt_version=prompt,
            requested_by=user,
        )
    return snapshot, prompt, job


def _bind(job, candidate, prompt, user):
    with lead_history_writes():
        return LeadAnalysisBinding.objects.create(
            organization=candidate.organization,
            job=job,
            candidate=candidate,
            prompt_version=prompt,
            requested_by=user,
        )


@pytest.mark.django_db
def test_worker_rejects_missing_durable_binding_and_recovers_owned_lease(
    candidate, evidence, approved_requirement, approved_capability, user
):
    Membership.objects.create(
        user=user,
        organization=candidate.organization,
        role=Role.objects.create_operator(),
    )
    snapshot = build_analysis_snapshot(
        candidate=candidate, evidence_ids=[evidence.id], actor=user
    )
    prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="missing-binding",
        provider="missing-binding-provider",
        model="fake-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=snapshot,
        created_by=user,
    )

    with pytest.raises(GenerationPreflightError, match="binding"):
        execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert not AIRun.objects.filter(job=job).exists()


@pytest.mark.django_db
def test_worker_rejects_prompt_that_differs_from_durable_binding_without_provider_call(
    candidate, evidence, approved_requirement, approved_capability, user
):
    snapshot, bound_prompt, job = _analysis_context(candidate, evidence, user)
    other_prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="mismatched-bound-prompt",
        provider="must-not-run",
        model="fake-v2",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    provider = SequenceProvider(
        [_valid_output(snapshot=snapshot, evidence_id=evidence.id)]
    )
    provider_registry.register("must-not-run", provider, replace=True)

    with pytest.raises(GenerationPreflightError, match="bound prompt"):
        execute_lead_analysis_job(job.id, other_prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert bound_prompt.id != other_prompt.id
    assert provider.calls == 0
    assert job.status == Job.Status.FAILED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_prompt_mismatch_redelivery_does_not_steal_running_worker_candidate_lease(
    candidate, evidence, approved_requirement, approved_capability, user
):
    _snapshot, _bound_prompt, job = _analysis_context(candidate, evidence, user)
    other_prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="running-mismatched-bound-prompt",
        provider="must-not-run",
        model="fake-v2",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    claimed = JobService.claim(worker_id="legal-worker", job_id=job.id)
    candidate.refresh_from_db()
    lease_token = candidate.analysis_lease_token
    candidate_version = candidate.version

    with pytest.raises(GenerationPreflightError, match="bound prompt"):
        execute_lead_analysis_job(job.id, other_prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert job.status == Job.Status.RUNNING
    assert job.claim_token == claimed.claim_token
    assert job.claimed_by == "legal-worker"
    assert job.error is None
    assert job.result_reference is None
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert candidate.analysis_lease_token == lease_token
    assert candidate.version == candidate_version
    assert not AIRun.objects.filter(job=job).exists()
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_provider_mismatch_redelivery_does_not_steal_running_worker_candidate_lease(
    candidate, evidence, approved_requirement, approved_capability, user
):
    _snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    claimed = JobService.claim(worker_id="legal-worker", job_id=job.id)
    candidate.refresh_from_db()
    lease_token = candidate.analysis_lease_token
    candidate_version = candidate.version

    with pytest.raises(GenerationPreflightError, match="provider"):
        execute_lead_analysis_job(
            job.id,
            prompt.id,
            provider_code="delayed-wrong-provider",
        )

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert job.status == Job.Status.RUNNING
    assert job.claim_token == claimed.claim_token
    assert job.claimed_by == "legal-worker"
    assert job.error is None
    assert job.result_reference is None
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert candidate.analysis_lease_token == lease_token
    assert candidate.version == candidate_version
    assert not AIRun.objects.filter(job=job).exists()
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_duplicate_terminal_preflight_redelivery_is_idempotent(
    candidate, evidence, approved_requirement, approved_capability, user
):
    _snapshot, _bound_prompt, job = _analysis_context(candidate, evidence, user)
    other_prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="terminal-mismatched-bound-prompt",
        provider="must-not-run",
        model="fake-v2",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )

    with pytest.raises(GenerationPreflightError, match="bound prompt"):
        execute_lead_analysis_job(job.id, other_prompt.id)
    job.refresh_from_db()
    candidate.refresh_from_db()
    failed_job_version = job.version
    candidate_version = candidate.version
    failed_at = job.finished_at

    with pytest.raises(GenerationPreflightError, match="bound prompt"):
        execute_lead_analysis_job(job.id, other_prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert job.version == failed_job_version
    assert job.finished_at == failed_at
    assert job.result_reference is None
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert candidate.version == candidate_version
    assert not AIRun.objects.filter(job=job).exists()
    assert not LeadInsight.objects.filter(candidate=candidate).exists()


@pytest.mark.django_db
def test_worker_rejects_tampered_binding_candidate_and_recovers_snapshot_owner(
    candidate,
    evidence,
    second_source_pair,
    approved_requirement,
    approved_capability,
    user,
):
    _snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    other = LeadCandidate.objects.create(
        organization=candidate.organization,
        source_signal=second_source_pair[0],
        company_name="Other Enterprise",
        created_by=user,
    )
    models.QuerySet.update(
        LeadAnalysisBinding._base_manager.filter(job=job), candidate=other
    )

    with pytest.raises(GenerationPreflightError, match="binding"):
        execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    other.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert other.status == LeadCandidate.Status.DISCOVERED


@pytest.mark.django_db
def test_worker_rejects_tampered_snapshot_and_recovers_durable_binding_owner(
    candidate, evidence, approved_requirement, approved_capability, user
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    tampered = deepcopy(snapshot)
    tampered["lead_candidate_id"] = "00000000-0000-4000-8000-000000000001"
    models.QuerySet.update(
        Job._base_manager.filter(pk=job.pk), input_snapshot=tampered
    )

    with pytest.raises(GenerationPreflightError, match="binding"):
        execute_lead_analysis_job(job.id, prompt.id)

    job.refresh_from_db()
    candidate.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None
    assert not AIRun.objects.filter(job=job).exists()


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
    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert candidate.analysis_lease_token is not None
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
    _bind(second_job, candidate, second_prompt, user)
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
@pytest.mark.parametrize(
    "manual_status",
    [LeadCandidate.Status.REVIEWED, LeadCandidate.Status.DISMISSED],
)
def test_active_reanalysis_lease_blocks_manual_transition(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
    manual_status,
):
    first_snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=first_snapshot, evidence_id=evidence.id)
    provider_registry.register("lead-sequence", SequenceProvider([output]), replace=True)
    execute_lead_analysis_job(job.id, prompt.id)

    build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    candidate.refresh_from_db()
    lease = candidate.analysis_lease_token

    with pytest.raises(LeadStateError, match="active analysis lease"):
        LeadService.transition(
            organization=candidate.organization,
            candidate=candidate,
            to_status=manual_status,
            expected_version=candidate.version,
        )

    candidate.refresh_from_db()
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert candidate.analysis_lease_token == lease


@pytest.mark.django_db
def test_failed_reanalysis_restores_analyzed_and_retry_reacquires_lease(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    first_snapshot, prompt, first_job = _analysis_context(candidate, evidence, user)
    first_output = _valid_output(snapshot=first_snapshot, evidence_id=evidence.id)
    provider_registry.register(
        "lead-sequence", SequenceProvider([first_output]), replace=True
    )
    execute_lead_analysis_job(first_job.id, prompt.id)

    second_snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    second_job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=second_snapshot,
        idempotency_key=f"retry-reanalysis-{candidate.id}",
        created_by=user,
    )
    _bind(second_job, candidate, prompt, user)
    valid = _valid_output(snapshot=second_snapshot, evidence_id=evidence.id)
    invalid = deepcopy(valid)
    invalid["reasons"][0]["evidence_ids"] = []
    provider_registry.register(
        "lead-sequence",
        SequenceProvider([invalid, invalid, valid]),
        replace=True,
    )

    failed = execute_lead_analysis_job(second_job.id, prompt.id)

    candidate.refresh_from_db()
    assert failed.status == AIRun.Status.FAILED
    assert candidate.status == LeadCandidate.Status.ANALYZED
    assert candidate.analysis_lease_token is None
    assert candidate.insights.count() == 1

    JobService.retry(second_job.id)
    succeeded = execute_lead_analysis_job(second_job.id, prompt.id)

    candidate.refresh_from_db()
    assert succeeded.status == AIRun.Status.SUCCEEDED
    assert candidate.status == LeadCandidate.Status.ANALYZED
    assert candidate.analysis_lease_token is None
    assert candidate.insights.count() == 2


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


@pytest.mark.django_db
def test_old_failed_job_redelivery_cannot_release_new_analysis_lease(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
    first_snapshot, prompt, first_job = _analysis_context(candidate, evidence, user)
    invalid = _valid_output(snapshot=first_snapshot, evidence_id=evidence.id)
    invalid["reasons"][0]["evidence_ids"] = []
    provider_registry.register(
        "lead-sequence", SequenceProvider([invalid, invalid]), replace=True
    )
    first_run = execute_lead_analysis_job(first_job.id, prompt.id)
    assert first_run.status == AIRun.Status.FAILED

    second_snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    second_job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=second_snapshot,
        idempotency_key=f"second-analysis-{candidate.id}",
        created_by=user,
    )
    _bind(second_job, candidate, prompt, user)
    candidate.refresh_from_db()
    second_lease = candidate.analysis_lease_token
    second_version = candidate.version

    duplicate = execute_lead_analysis_job(first_job.id, prompt.id)

    candidate.refresh_from_db()
    assert duplicate.id == first_run.id
    assert second_job.status == Job.Status.QUEUED
    assert candidate.status == LeadCandidate.Status.ANALYZING
    assert candidate.analysis_lease_token == second_lease
    assert candidate.version == second_version


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_status", [Job.Status.CANCELED, Job.Status.FAILED])
def test_orphaned_running_airun_reconciles_without_provider_or_stale_recovery(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
    terminal_status,
):
    snapshot, prompt, job = _analysis_context(candidate, evidence, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    provider = SequenceProvider([output])
    provider_registry.register("lead-sequence", provider, replace=True)
    claimed = JobService.claim(worker_id="crashed-worker", job_id=job.id)
    with ai_audit_writes():
        run = AIRun.objects.create(
            organization=job.organization,
            job=job,
            job_attempt=job.attempt,
            prompt_version=prompt,
            provider="lead-sequence",
            model=prompt.model,
            input_snapshot=job.input_snapshot,
            status=AIRun.Status.RUNNING,
            started_at=timezone.now(),
        )
    if terminal_status == Job.Status.CANCELED:
        JobService.cancel(job.id)
    else:
        JobService.fail(
            job.id,
            claim_token=claimed.claim_token,
            error={"code": "provider_error"},
        )

    duplicate = execute_lead_analysis_job(job.id, prompt.id)

    candidate.refresh_from_db()
    duplicate.refresh_from_db()
    assert duplicate.id == run.id
    assert duplicate.status == (
        AIRun.Status.CANCELED
        if terminal_status == Job.Status.CANCELED
        else AIRun.Status.FAILED
    )
    assert duplicate.finished_at is not None
    assert provider.calls == 0
    assert candidate.status == LeadCandidate.Status.DISCOVERED
    assert candidate.analysis_lease_token is None


@pytest.mark.django_db
def test_cross_type_same_code_binds_requirement_and_capability_unambiguously(
    candidate,
    evidence,
    user,
):
    Membership.objects.create(
        user=user,
        organization=candidate.organization,
        role=Role.objects.create_operator(),
    )
    with _test_fixture_writes():
        requirement = KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.ORGANIZATION,
            organization=candidate.organization,
            concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
            code="SHARED_CODE",
            label_zh="共享编码要求",
            label_en="Shared-code requirement",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
        capability = KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.SYSTEM,
            organization=None,
            concept_type=KnowledgeConcept.ConceptType.CAPABILITY,
            code="SHARED_CODE",
            label_zh="共享编码能力",
            label_en="Shared-code capability",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
        knowledge_evidence = KnowledgeEvidence.objects.create(
            organization=None,
            evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
            excerpt="Evidence for the shared-code capability.",
            status=KnowledgeStatus.APPROVED,
            created_by=user,
        )
    KnowledgeConceptEvidence.objects.create(
        knowledgeconcept=capability,
        knowledgeevidence=knowledge_evidence,
    )
    snapshot = build_analysis_snapshot(
        candidate=candidate,
        evidence_ids=[evidence.id],
        actor=user,
    )
    prompt = PromptVersionService.create(
        purpose="LEAD_ANALYZE",
        code="cross-type-code",
        provider="lead-cross-type",
        model="fake-lead-v1",
        template="{input_json}",
        output_schema=LEAD_ANALYSIS_OUTPUT_SCHEMA,
        status=PromptVersion.Status.PUBLISHED,
        created_by=user,
    )
    job = JobService.create(
        organization=candidate.organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=snapshot,
        created_by=user,
    )
    _bind(job, candidate, prompt, user)
    output = _valid_output(snapshot=snapshot, evidence_id=evidence.id)
    output["requirements"][0]["type"] = "SHARED_CODE"
    output["capability_matches"][0] = {
        "capability_code": "SHARED_CODE",
        "knowledge_evidence_ids": [str(knowledge_evidence.id)],
        "source_evidence_ids": [str(evidence.id)],
    }
    provider_registry.register(
        "lead-cross-type", SequenceProvider([output]), replace=True
    )

    run = execute_lead_analysis_job(job.id, prompt.id)

    link = LeadInsight.objects.get(ai_run=run).requirements.get()
    assert link.requirement_concept_id == requirement.id
    assert link.capability_concept_id == capability.id


@pytest.mark.django_db
def test_retry_cannot_claim_candidate_without_frozen_lease(candidate):
    with pytest.raises(LeadStateError):
        LeadService.resume_analysis_retry(
            organization_id=candidate.organization_id,
            candidate_id=candidate.id,
            started_from=LeadCandidate.Status.DISCOVERED,
            analysis_lease_token=None,
        )
