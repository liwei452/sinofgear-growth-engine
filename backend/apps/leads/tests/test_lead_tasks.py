import pytest

from apps.ai.models import AIRun, PromptVersion
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.knowledge.models import KnowledgeGraphLock
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.leads.services import build_analysis_snapshot
from apps.leads.tasks import execute_lead_analysis
from integrations.ai.providers import provider_registry

from .test_analysis_snapshot import _valid_output
from .test_lead_orchestration import SequenceProvider


@pytest.fixture(autouse=True)
def ensure_graph_lock(db):
    KnowledgeGraphLock.objects.get_or_create(pk=1, defaults={"name": "is_a_graph"})


@pytest.mark.django_db(transaction=True)
def test_lead_analysis_task_returns_durable_result_ids(
    candidate,
    evidence,
    approved_requirement,
    approved_capability,
    user,
):
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
        code="lead-task-test",
        provider="lead-task",
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
    provider_registry.register(
        "lead-task",
        SequenceProvider([_valid_output(snapshot=snapshot, evidence_id=evidence.id)]),
        replace=True,
    )

    result = execute_lead_analysis.delay(str(job.id), str(prompt.id)).get()

    job.refresh_from_db()
    assert result == {**job.result_reference, "status": AIRun.Status.SUCCEEDED}
