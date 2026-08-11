from io import StringIO
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings

from apps.ai.models import AIRun, PromptVersion
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job, JobAttempt, job_service_writes
from apps.leads.models import LeadCandidate, LeadInsight, LeadReview
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA
from apps.sources.models import (
    IngestionBatch,
    IngestionRow,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)


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


def _run_seed(organization, user):
    call_command(
        "seed_phase_b1",
        organization_slug=organization.slug,
        username=user.username,
        stdout=StringIO(),
    )


def _raw_update(model, pk, **values):
    assignments = []
    parameters = []
    quote = connection.ops.quote_name
    for field_name, value in values.items():
        try:
            field = model._meta.get_field(field_name)
        except FieldDoesNotExist:
            if not field_name.endswith("_id"):
                raise
            field = model._meta.get_field(field_name[:-3])
        assignments.append(f"{quote(field.column)} = %s")
        parameters.append(field.get_db_prep_save(value, connection))
    parameters.append(model._meta.pk.get_db_prep_save(pk, connection))
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {quote(model._meta.db_table)} "
            f"SET {', '.join(assignments)} WHERE {quote(model._meta.pk.column)} = %s",
            parameters,
        )


def _source_contract_counts():
    source_import_jobs = Job.objects.filter(type=Job.Type.SOURCE_IMPORT)
    return {
        "targets": MonitoringTarget.objects.count(),
        "batches": IngestionBatch.objects.count(),
        "rows": IngestionRow.objects.count(),
        "contents": SourceContent.objects.count(),
        "signals": SourceSignal.objects.count(),
        "evidence": SourceEvidence.objects.count(),
        "import_jobs": source_import_jobs.count(),
        "import_attempts": JobAttempt.objects.filter(
            job__in=source_import_jobs
        ).count(),
    }


def _source_contract_tamper(case, *, organization, other_organization, other_user):
    batch = IngestionBatch.objects.select_related("monitoring_target", "job").get(
        organization=organization
    )
    accepted = batch.rows.select_related(
        "source_content", "source_signal", "source_evidence"
    ).get(row_number=1)
    failed = batch.rows.get(row_number=4)
    other_signal = batch.rows.get(row_number=2).source_signal
    import_attempt = batch.job.attempts.get(number=1)
    cases = {
        "target_external_reference": (
            batch.monitoring_target,
            "external_reference",
            "tampered-reference",
            "monitoring target",
        ),
        "target_normalized_url": (
            batch.monitoring_target,
            "normalized_url",
            "https://example.com/phase-b1/tampered-target",
            "monitoring target",
        ),
        "target_capability_snapshot": (
            batch.monitoring_target,
            "capability_snapshot",
            {"tampered": True},
            "monitoring target",
        ),
        "target_enabled": (
            batch.monitoring_target,
            "enabled",
            False,
            "monitoring target",
        ),
        "target_organization": (
            batch.monitoring_target,
            "organization_id",
            other_organization.id,
            "monitoring target",
        ),
        "batch_received_count": (
            batch,
            "received_count",
            99,
            "mixed import",
        ),
        "batch_row_errors": (
            batch,
            "row_errors",
            [{"tampered": True}],
            "mixed import",
        ),
        "batch_request_digest": (
            batch,
            "prepared_reference_sha256",
            "f" * 64,
            "mixed import",
        ),
        "batch_request_asset": (
            batch,
            "request_import_asset_id",
            uuid4(),
            "mixed import",
        ),
        "batch_organization": (
            batch,
            "organization_id",
            other_organization.id,
            "mixed import",
        ),
        "job_status": (batch.job, "status", Job.Status.FAILED, "import job"),
        "job_input_snapshot": (
            batch.job,
            "input_snapshot",
            {"tampered": True},
            "import job",
        ),
        "job_result_reference": (
            batch.job,
            "result_reference",
            {"tampered": True},
            "import job",
        ),
        "job_error": (
            batch.job,
            "error",
            {"code": "tampered"},
            "import job",
        ),
        "job_created_by": (
            batch.job,
            "created_by_id",
            other_user.id,
            "import job",
        ),
        "job_organization": (
            batch.job,
            "organization_id",
            other_organization.id,
            "import job",
        ),
        "job_attempt_status": (
            import_attempt,
            "status",
            JobAttempt.Status.FAILED,
            "import job attempt",
        ),
        "row_normalized_input": (
            accepted,
            "normalized_input",
            {"tampered": True},
            "ingestion row",
        ),
        "row_outcome": (
            accepted,
            "outcome",
            IngestionRow.Outcome.FAILED,
            "ingestion row",
        ),
        "row_source_evidence": (
            accepted,
            "source_evidence_id",
            None,
            "ingestion row",
        ),
        "row_error": (
            failed,
            "error",
            {"tampered": True},
            "ingestion row",
        ),
        "row_organization": (
            accepted,
            "organization_id",
            other_organization.id,
            "ingestion row",
        ),
        "content_hash": (
            accepted.source_content,
            "content_hash",
            "e" * 64,
            "source content",
        ),
        "content_original_text": (
            accepted.source_content,
            "original_text",
            "Tampered source content.",
            "source content",
        ),
        "content_captured_at": (
            accepted.source_content,
            "captured_at",
            datetime(2030, 1, 1, tzinfo=UTC),
            "source content",
        ),
        "content_target": (
            accepted.source_content,
            "monitoring_target_id",
            None,
            "source content",
        ),
        "content_created_by": (
            accepted.source_content,
            "created_by_id",
            other_user.id,
            "source content",
        ),
        "signal_type": (
            accepted.source_signal,
            "signal_type",
            SourceSignal.SignalType.COMMENT,
            "source signal",
        ),
        "signal_captured_at": (
            accepted.source_signal,
            "captured_at",
            datetime(2030, 1, 1, tzinfo=UTC),
            "source signal",
        ),
        "signal_source_content": (
            accepted.source_signal,
            "source_content_id",
            None,
            "source signal",
        ),
        "signal_created_by": (
            accepted.source_signal,
            "created_by_id",
            other_user.id,
            "source signal",
        ),
        "evidence_hash": (
            accepted.source_evidence,
            "content_hash",
            "d" * 64,
            "source evidence",
        ),
        "evidence_captured_at": (
            accepted.source_evidence,
            "captured_at",
            datetime(2030, 1, 1, tzinfo=UTC),
            "source evidence",
        ),
        "evidence_signal": (
            accepted.source_evidence,
            "source_signal_id",
            other_signal.id,
            "source evidence",
        ),
        "evidence_availability": (
            accepted.source_evidence,
            "availability",
            SourceEvidence.Availability.SOURCE_UNAVAILABLE,
            "source evidence",
        ),
        "evidence_created_by": (
            accepted.source_evidence,
            "created_by_id",
            other_user.id,
            "source evidence",
        ),
        "evidence_organization": (
            accepted.source_evidence,
            "organization_id",
            other_organization.id,
            "source evidence",
        ),
    }
    instance, field_name, tampered_value, error_label = cases[case]
    return type(instance), instance.pk, field_name, tampered_value, error_label


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
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


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_candidate_country_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    candidate = LeadCandidate.objects.get(
        organization=organization,
        company_name="Phase B1 Browser Packaging",
    )
    candidate.country_hint = "US"
    candidate.save(update_fields=["country_hint"])

    with pytest.raises(CommandError, match="candidate"):
        _run_seed(organization, user)

    candidate.refresh_from_db()
    assert candidate.country_hint == "US"


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_existing_insight_output_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    candidate = LeadCandidate.objects.get(
        organization=organization,
        company_name="Phase B1 Browser Packaging",
    )
    tampered = json.dumps(
        {"reasons": [{"text": "invented", "evidence_ids": []}]},
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE leads_leadinsight SET explanation = %s WHERE id = %s",
            [tampered, candidate.latest_insight_id.hex],
        )

    with pytest.raises(CommandError, match="analysis"):
        _run_seed(organization, user)


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_existing_review_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    review = LeadReview.objects.get(
        organization=organization,
        idempotency_key="phase-b1-seed-reviewed-correction",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE leads_leadreview SET reason = %s WHERE id = %s",
            ["Tampered reviewer reason.", review.id.hex],
        )

    with pytest.raises(CommandError, match="review"):
        _run_seed(organization, user)


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_existing_failed_job_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    job = Job.objects.get(
        organization=organization,
        idempotency_key="phase-b1-seed-failed-analysis",
    )
    with job_service_writes():
        Job.objects.filter(pk=job.pk).update(
            status=Job.Status.SUCCEEDED,
            error=None,
            result_reference={"tampered": True},
        )

    with pytest.raises(CommandError, match="failed job"):
        _run_seed(organization, user)


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_monitoring_target_schedule_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    target = MonitoringTarget.objects.get(organization=organization)
    target.schedule = {"tampered": True}
    target.save(update_fields=["schedule", "updated_at"])

    with pytest.raises(CommandError, match="monitoring target"):
        _run_seed(organization, user)

    target.refresh_from_db()
    assert target.schedule == {"tampered": True}


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_ingestion_batch_count_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    batch = IngestionBatch.objects.get(organization=organization)
    batch.accepted_count = 99
    batch.save(update_fields=["accepted_count", "updated_at"])

    with pytest.raises(CommandError, match="mixed import"):
        _run_seed(organization, user)

    batch.refresh_from_db()
    assert batch.accepted_count == 99


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
def test_seed_phase_b1_rejects_source_evidence_text_collision(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    evidence = SourceEvidence.objects.get(
        organization=organization,
        source_url="https://example.com/phase-b1/public-signal",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_sourceevidence SET original_text = %s WHERE id = %s",
            ["Tampered public evidence.", evidence.id.hex],
        )

    with pytest.raises(CommandError, match="evidence"):
        _run_seed(organization, user)

    evidence.refresh_from_db()
    assert evidence.original_text == "Tampered public evidence."


@pytest.mark.django_db(transaction=True)
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
@pytest.mark.parametrize(
    "case",
    [
        "target_external_reference",
        "target_normalized_url",
        "target_capability_snapshot",
        "target_enabled",
        "target_organization",
        "batch_received_count",
        "batch_row_errors",
        "batch_request_digest",
        "batch_request_asset",
        "batch_organization",
        "job_status",
        "job_input_snapshot",
        "job_result_reference",
        "job_error",
        "job_created_by",
        "job_organization",
        "job_attempt_status",
        "row_normalized_input",
        "row_outcome",
        "row_source_evidence",
        "row_error",
        "row_organization",
        "content_hash",
        "content_original_text",
        "content_captured_at",
        "content_target",
        "content_created_by",
        "signal_type",
        "signal_captured_at",
        "signal_source_content",
        "signal_created_by",
        "evidence_hash",
        "evidence_captured_at",
        "evidence_signal",
        "evidence_availability",
        "evidence_created_by",
        "evidence_organization",
    ],
)
def test_seed_phase_b1_rejects_owned_source_contract_matrix(
    phase_b1_seed_identity,
    case,
):
    organization, user = phase_b1_seed_identity
    _run_seed(organization, user)
    other_organization = Organization.objects.create(
        name=f"Other {case}", slug=f"other-{case.replace('_', '-')}"
    )
    other_user = get_user_model().objects.create_user(username=f"other_{case}")
    model, pk, field_name, tampered_value, error_label = _source_contract_tamper(
        case,
        organization=organization,
        other_organization=other_organization,
        other_user=other_user,
    )
    _raw_update(model, pk, **{field_name: tampered_value})
    counts_after_tamper = _source_contract_counts()

    with pytest.raises(CommandError, match=error_label):
        _run_seed(organization, user)

    assert _source_contract_counts() == counts_after_tamper
    persisted = model.objects.get(pk=pk)
    assert getattr(persisted, field_name) == tampered_value


@pytest.mark.django_db
@override_settings(PHASE_B1_SCHEMA_FAKE_ALLOWED=True)
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


@pytest.mark.django_db
def test_seed_phase_b1_fails_closed_before_publishing_a_fake_prompt(
    phase_b1_seed_identity,
):
    organization, user = phase_b1_seed_identity

    with pytest.raises(CommandError, match="schema-fake safety gate"):
        call_command(
            "seed_phase_b1",
            organization_slug=organization.slug,
            username=user.username,
        )

    assert not PromptVersion.objects.filter(purpose="LEAD_ANALYZE").exists()
    assert _seed_counts(organization) == {
        "targets": 0,
        "batches": 0,
        "evidence": 0,
        "candidates": 0,
        "insights": 0,
        "reviews": 0,
        "jobs": 0,
        "runs": 0,
    }


@pytest.mark.django_db(transaction=True)
@override_settings(
    PHASE_A_E2E_SEED_ALLOWED=True,
    PHASE_B1_SCHEMA_FAKE_ALLOWED=True,
)
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
