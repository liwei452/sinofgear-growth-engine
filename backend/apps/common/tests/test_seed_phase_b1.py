from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.ai.models import AIRun, PromptVersion
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job
from apps.leads.models import LeadCandidate, LeadInsight, LeadReview
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.sources.models import IngestionBatch, MonitoringTarget, SourceEvidence


@pytest.fixture
def phase_b1_seed_identity(db):
    organization = Organization.objects.create(
        name="Phase B1 Seed Test", slug="phase-b1-seed-test"
    )
    user = get_user_model().objects.create_user(username="phaseb1_seed_admin")
    Membership.objects.create(
        organization=organization,
        user=user,
        role=Role.objects.create_administrator(),
    )
    return organization, user


def _seed_counts(organization):
    return {
        "targets": MonitoringTarget.objects.filter(organization=organization).count(),
        "batches": IngestionBatch.objects.filter(organization=organization).count(),
        "evidence": SourceEvidence.objects.filter(organization=organization).count(),
        "candidates": LeadCandidate.objects.filter(organization=organization).count(),
        "insights": LeadInsight.objects.filter(organization=organization).count(),
        "reviews": LeadReview.objects.filter(organization=organization).count(),
        "jobs": Job.objects.filter(organization=organization).count(),
        "runs": AIRun.objects.filter(organization=organization).count(),
    }


@pytest.mark.django_db(transaction=True)
def test_seed_phase_b1_is_complete_and_idempotent(phase_b1_seed_identity):
    organization, user = phase_b1_seed_identity
    arguments = [
        "seed_phase_b1",
        "--organization-slug",
        organization.slug,
        "--username",
        user.username,
    ]

    first_output = StringIO()
    call_command(*arguments, stdout=first_output)
    first_counts = _seed_counts(organization)
    second_output = StringIO()
    call_command(*arguments, stdout=second_output)

    assert _seed_counts(organization) == first_counts
    assert first_counts == {
        "targets": 1,
        "batches": 1,
        "evidence": 3,
        "candidates": 4,
        "insights": 5,
        "reviews": 1,
        "jobs": 6,
        "runs": 4,
    }
    batch = IngestionBatch.objects.get(organization=organization)
    assert batch.status == IngestionBatch.Status.PARTIAL_SUCCESS
    assert (batch.accepted_count, batch.failed_count) == (3, 1)
    assert set(
        LeadInsight.objects.filter(organization=organization).values_list(
            "score_band", flat=True
        )
    ) == {"LOW", "WATCH", "HIGH"}
    correction = LeadReview.objects.get(organization=organization)
    assert correction.action == LeadReview.Action.CORRECT
    assert correction.reason == "Seeded reviewer correction for acceptance testing."
    assert (
        Job.objects.filter(
            organization=organization,
            type=Job.Type.LEAD_ANALYZE,
            status=Job.Status.FAILED,
            idempotency_key="phase-b1-seed-failed-analysis",
        ).count()
        == 1
    )

    prompt = PromptVersion.objects.get(code="phase-b1-lead-analyze-v1")
    assert prompt.purpose == "LEAD_ANALYZE"
    assert prompt.status == PromptVersion.Status.PUBLISHED
    assert prompt.provider == "schema-fake"
    assert prompt.output_schema == LEAD_ANALYSIS_OUTPUT_SCHEMA
    assert "{input_json}" in prompt.template
    assert "Phase B1 seed present" in first_output.getvalue()
    assert "Phase B1 seed present" in second_output.getvalue()


@pytest.mark.django_db
def test_seed_phase_b1_requires_an_active_named_membership():
    organization = Organization.objects.create(
        name="No Membership", slug="no-membership"
    )
    user = get_user_model().objects.create_user(username="no_membership_user")

    with pytest.raises(CommandError, match="active membership"):
        call_command(
            "seed_phase_b1",
            organization_slug=organization.slug,
            username=user.username,
        )


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_A_E2E_SEED_ALLOWED=True)
def test_seed_phase_b1_can_create_an_explicit_isolated_e2e_identity():
    call_command(
        "seed_phase_b1",
        organization_slug="phase-b1-e2e-foreign",
        organization_name="Phase B1 E2E Foreign",
        username="phaseb1_e2e_foreign",
        password="PhaseA-E2E-Only!",
        create_demo_identity=True,
        stdout=StringIO(),
    )

    organization = Organization.objects.get(slug="phase-b1-e2e-foreign")
    user = get_user_model().objects.get(username="phaseb1_e2e_foreign")
    membership = Membership.objects.get(organization=organization, user=user)
    assert membership.role.code == Role.Code.ADMINISTRATOR
    assert user.check_password("PhaseA-E2E-Only!")
    assert user.email == "phaseb1_e2e_foreign@example.invalid"
    assert LeadCandidate.objects.filter(organization=organization).count() == 4
    assert SourceEvidence.objects.filter(organization=organization).count() == 3
