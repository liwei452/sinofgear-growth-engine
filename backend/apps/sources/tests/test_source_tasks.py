import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.assets.models import MaterialAsset
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.sources.importers import prepare_import_reference
from apps.sources.models import (
    IngestionBatch,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
    evidence_service_writes,
)
from apps.sources.services import (
    EvidenceService,
    IngestionService,
    RetentionService,
    retention_cleanup_job_snapshot,
)
from apps.sources.tasks import execute_retention_cleanup, execute_source_import


def _snapshot(batch):
    digest = hashlib.sha256(
        json.dumps(
            batch.input_reference,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "SOURCE_IMPORT_JOB_V1",
        "ingestion_batch_id": str(batch.id),
        "source_type": batch.source_type,
        "monitoring_target_id": (
            str(batch.monitoring_target_id) if batch.monitoring_target_id else None
        ),
        "prepared_reference_sha256": digest,
        "import_asset_id": batch.input_reference.get("import_asset_id"),
        "batch_idempotency_key": batch.idempotency_key,
    }


def make_batch(
    *,
    organization,
    user,
    key="worker-batch",
    source_type=IngestionBatch.SourceType.URL,
    payload=None,
    target=None,
):
    if payload is None:
        payload = {
            "source_url": "https://e.test/worker",
            "original_text": "Need replacement gear",
        }
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=source_type,
        input_reference=prepare_import_reference(payload, source_type=source_type),
        idempotency_key=key,
        monitoring_target=target,
        created_by=user,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot=_snapshot(batch),
        idempotency_key=key,
        created_by=user,
    )
    batch.job = job
    batch.save(update_fields=["job", "updated_at"])
    return batch


def _assert_preflight_failed(batch, result):
    job = batch.job
    job.refresh_from_db()
    batch.refresh_from_db()
    assert result == {"ingestion_batch_id": str(batch.id), "status": "FAILED"}
    assert job.status == Job.Status.FAILED
    assert job.error == {
        "code": "SOURCE_IMPORT_FAILED",
        "message": "Public source import failed.",
    }
    assert batch.status == IngestionBatch.Status.FAILED
    assert batch.started_at is None
    assert batch.rows.count() == 0
    assert SourceEvidence.objects.count() == 0
    assert batch.row_errors == [
        {
            "row": None,
            "code": "SOURCE_IMPORT_PREFLIGHT_FAILED",
            "recovery_action": "Review the source import configuration and retry.",
        }
    ]


def make_retention_job(*, organization, cutoff, key="retention-worker"):
    return JobService.create(
        organization=organization,
        job_type=Job.Type.RETENTION_CLEANUP,
        input_snapshot=retention_cleanup_job_snapshot(
            organization=organization,
            cutoff=cutoff,
        ),
        idempotency_key=key,
        created_by=None,
    )


def make_old_evidence(*, organization, signal, user, cutoff):
    evidence = EvidenceService.create(
        organization=organization,
        signal=signal,
        original_text="Old worker retention text",
        source_url="https://example.com/posts/42",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.PASTE,
        public_published_at=cutoff - timedelta(days=1),
        created_by=user,
    )
    with evidence_service_writes():
        evidence.captured_at = cutoff - timedelta(days=1)
        evidence.save(update_fields=["captured_at", "updated_at"])
    return evidence


@pytest.mark.django_db
def test_worker_claims_runs_and_succeeds_job(organization, job, user):
    batch = make_batch(organization=organization, user=user)
    job = batch.job

    result = execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    batch.refresh_from_db()
    assert result == {"ingestion_batch_id": str(batch.id), "status": "SUCCEEDED"}
    assert job.status == Job.Status.SUCCEEDED
    assert job.result_reference == {"ingestion_batch_id": str(batch.id)}
    assert batch.status == IngestionBatch.Status.SUCCEEDED


@pytest.mark.django_db
def test_worker_failure_marks_owned_job_failed_and_reraises(
    organization, job, user, monkeypatch
):
    batch = make_batch(organization=organization, user=user, key="worker-failure")
    job = batch.job

    def fail_run(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(IngestionService, "run", fail_run)

    with pytest.raises(RuntimeError, match="database unavailable"):
        execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert job.error == {
        "code": "SOURCE_IMPORT_FAILED",
        "message": "Public source import failed.",
    }


@pytest.mark.django_db
def test_worker_does_not_mask_original_failure_when_claim_becomes_stale(
    organization, job, user, monkeypatch
):
    batch = make_batch(organization=organization, user=user, key="worker-stale")
    job = batch.job

    def cancel_then_fail(**_kwargs):
        JobService.cancel(job.id, organization=organization)
        raise RuntimeError("original ingestion failure")

    monkeypatch.setattr(IngestionService, "run", cancel_then_fail)

    with pytest.raises(RuntimeError, match="original ingestion failure"):
        execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    assert job.status == Job.Status.CANCELED


@pytest.mark.django_db
def test_worker_without_a_claimable_job_leaves_state_unchanged(organization, job, user):
    batch = make_batch(organization=organization, user=user, key="worker-unchanged")
    job = batch.job
    claimed = JobService.claim(worker_id="another-worker", job_id=job.id)

    result = execute_source_import(str(job.id), str(batch.id))

    job.refresh_from_db()
    batch.refresh_from_db()
    assert result == {"job_id": str(job.id), "status": "UNCHANGED"}
    assert job.status == Job.Status.RUNNING
    assert job.claim_token == claimed.claim_token
    assert batch.status == IngestionBatch.Status.QUEUED


@pytest.mark.django_db
def test_worker_rejects_batch_identity_drift_before_running_or_creating_rows(
    organization, user
):
    batch = make_batch(organization=organization, user=user, key="worker-drift")
    job = batch.job
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET idempotency_key = %s WHERE id = %s",
            ["worker-drift-tampered", batch.id.hex],
        )

    result = execute_source_import(str(job.id), str(batch.id))

    _assert_preflight_failed(batch, result)


@pytest.mark.django_db
def test_worker_terminalizes_batch_with_database_corrupted_prepared_reference(
    organization, user
):
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-corrupt-reference",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET input_reference = %s WHERE id = %s",
            [json.dumps("corrupted raw reference"), batch.id.hex],
        )

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)
    assert SourceContent.objects.count() == 0
    assert SourceSignal.objects.count() == 0


@pytest.mark.django_db
def test_worker_rejects_valid_but_identity_changed_raw_reference(
    organization, user
):
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-valid-reference-drift",
    )
    changed = prepare_import_reference(
        {
            "source_url": "https://e.test/changed-after-binding",
            "original_text": "Changed after immutable binding",
        },
        source_type=IngestionBatch.SourceType.URL,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET input_reference = %s WHERE id = %s",
            [json.dumps(changed), batch.id.hex],
        )

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)
    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_worker_terminalizes_batch_with_database_corrupted_cross_org_target(
    organization, other_organization, user, target
):
    foreign_target = MonitoringTarget.objects.create(
        organization=other_organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.MANUAL_URL,
        platform="MANUAL",
        normalized_url="https://foreign.test/source",
        label="Foreign target",
        created_by=user,
    )
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-cross-org-target",
        target=target,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET monitoring_target_id = %s WHERE id = %s",
            [foreign_target.id.hex, batch.id.hex],
        )

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)
    assert SourceContent.objects.count() == 0
    assert SourceSignal.objects.count() == 0


@pytest.mark.django_db
def test_retention_worker_claims_redacts_and_persists_bounded_counts(
    organization, signal, user
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = make_old_evidence(
        organization=organization,
        signal=signal,
        user=user,
        cutoff=cutoff,
    )
    job = make_retention_job(organization=organization, cutoff=cutoff)

    result = execute_retention_cleanup(str(job.id))

    job.refresh_from_db()
    evidence.refresh_from_db()
    assert job.status == Job.Status.SUCCEEDED
    assert job.result_reference == {
        "policy_version": "SOURCE_EVIDENCE_RETENTION_V1",
        "redacted": 1,
        "deleted_text": 2,
        "anonymized_actors": 0,
        "protected": 0,
        "failures": 0,
        "no_op": 0,
    }
    assert result == {"job_id": str(job.id), "status": "SUCCEEDED", **job.result_reference}
    assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION

    duplicate = execute_retention_cleanup(str(job.id))
    assert duplicate == {"job_id": str(job.id), "status": "UNCHANGED"}


@pytest.mark.django_db
def test_retention_worker_cannot_redact_after_ownership_is_canceled(
    organization, signal, user
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = make_old_evidence(
        organization=organization,
        signal=signal,
        user=user,
        cutoff=cutoff,
    )
    job = make_retention_job(
        organization=organization,
        cutoff=cutoff,
        key="retention-canceled",
    )
    claimed = JobService.claim(
        worker_id="source-retention-worker",
        job_id=job.id,
        job_type=Job.Type.RETENTION_CLEANUP,
    )
    claim_token = claimed.claim_token
    JobService.cancel(job.id, organization=organization)
    with pytest.raises(Exception, match="no longer owns"):
        RetentionService.cleanup_owned(
            organization=organization,
            cutoff=cutoff,
            actor=None,
            job_id=job.id,
            claim_token=claim_token,
        )

    job.refresh_from_db()
    evidence.refresh_from_db()
    assert job.status == Job.Status.CANCELED
    assert evidence.original_text == "Old worker retention text"
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert execute_retention_cleanup(str(job.id)) == {
        "job_id": str(job.id),
        "status": "UNCHANGED",
    }


@pytest.mark.django_db
def test_retention_worker_rejects_tampered_job_identity_without_redaction(
    organization, signal, user
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = make_old_evidence(
        organization=organization,
        signal=signal,
        user=user,
        cutoff=cutoff,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.RETENTION_CLEANUP,
        input_snapshot={
            "schema": "SOURCE_RETENTION_JOB_V1",
            "organization_id": str(uuid4()),
            "cutoff": cutoff.isoformat(),
            "policy_version": "SOURCE_EVIDENCE_RETENTION_V1",
        },
        idempotency_key="retention-tampered",
        created_by=None,
    )

    with pytest.raises(Exception, match="does not match"):
        execute_retention_cleanup(str(job.id))

    job.refresh_from_db()
    evidence.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert evidence.original_text == "Old worker retention text"


@pytest.mark.django_db
def test_worker_preflight_rejects_target_disabled_after_queue(
    organization, user, target
):
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-disabled-target",
        target=target,
    )
    target.enabled = False
    target.save(update_fields=["enabled", "updated_at"])

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)


@pytest.mark.django_db
def test_worker_preflight_checks_archived_import_asset_even_with_no_rows(
    organization, user, asset
):
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-empty-archived-import",
        source_type=IngestionBatch.SourceType.PASTE,
        payload={"text": "", "import_asset_id": str(asset.id)},
    )
    asset.status = MaterialAsset.Status.ARCHIVED
    asset.save(update_fields=["status", "updated_at"])

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)


@pytest.mark.django_db
@pytest.mark.parametrize("asset_state", ["archived", "foreign", "missing"])
def test_worker_preflight_rejects_every_unavailable_screenshot_before_rows(
    asset_state, organization, user, asset, other_asset
):
    screenshot_id = asset.id
    if asset_state == "foreign":
        screenshot_id = other_asset.id
    elif asset_state == "missing":
        screenshot_id = uuid4()
    batch = make_batch(
        organization=organization,
        user=user,
        key=f"worker-screenshot-{asset_state}",
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        payload={
            "source_url": f"https://e.test/screenshot/{asset_state}",
            "original_text": "Need gear",
            "screenshot_asset_id": str(screenshot_id),
        },
    )
    if asset_state == "archived":
        asset.status = MaterialAsset.Status.ARCHIVED
        asset.save(update_fields=["status", "updated_at"])

    result = execute_source_import(str(batch.job_id), str(batch.id))

    _assert_preflight_failed(batch, result)


@pytest.mark.django_db
def test_worker_preflight_resolves_screenshot_references_in_one_bounded_query(
    organization, user, asset, other_asset
):
    missing_id = uuid4()
    batch = make_batch(
        organization=organization,
        user=user,
        key="worker-screenshot-bounded",
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "rows": [
                {
                    "source_url": "https://e.test/screenshot/owned",
                    "original_text": "Owned",
                    "screenshot_asset_id": str(asset.id),
                },
                {
                    "source_url": "https://e.test/screenshot/foreign",
                    "original_text": "Foreign",
                    "screenshot_asset_id": str(other_asset.id),
                },
                {
                    "source_url": "https://e.test/screenshot/missing",
                    "original_text": "Missing",
                    "screenshot_asset_id": str(missing_id),
                },
            ]
        },
    )

    with CaptureQueriesContext(connection) as queries:
        result = execute_source_import(str(batch.job_id), str(batch.id))

    asset_queries = [
        query["sql"]
        for query in queries.captured_queries
        if "assets_materialasset" in query["sql"].lower()
    ]
    assert len(asset_queries) == 1
    _assert_preflight_failed(batch, result)
