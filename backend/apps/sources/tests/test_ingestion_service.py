from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, InterfaceError

from apps.assets.models import MaterialAsset
from apps.jobs.services import JobService, StaleJobWorkerError
from apps.sources.importers import prepare_import_reference
from apps.sources.models import (
    IngestionBatch,
    IngestionRow,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from apps.sources.services import IngestionService


def make_batch(*, organization, job, source_type, payload, key, user, target=None):
    input_reference = prepare_import_reference(payload, source_type=source_type)
    return IngestionBatch.objects.create(
        organization=organization,
        job=job,
        monitoring_target=target,
        source_type=source_type,
        input_reference=input_reference,
        idempotency_key=key,
        created_by=user,
    )


@pytest.mark.django_db
def test_ingestion_partial_success_persists_each_row_and_recomputes_statistics(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.CSV,
        payload={
            "text": (
                "source_url,original_text\n"
                "https://e.test/1,Need gear\n"
                ",Missing URL"
            )
        },
        key="partial-csv",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.PARTIAL_SUCCESS
    assert (
        result.received_count,
        result.accepted_count,
        result.duplicate_count,
        result.failed_count,
    ) == (2, 1, 0, 1)
    assert list(result.rows.values_list("row_number", "outcome")) == [
        (2, IngestionRow.Outcome.ACCEPTED),
        (3, IngestionRow.Outcome.FAILED),
    ]
    assert result.row_errors[0]["code"] == "SOURCE_URL_REQUIRED"
    assert SourceContent.objects.count() == 1
    assert SourceSignal.objects.count() == 1
    assert SourceEvidence.objects.count() == 1


@pytest.mark.django_db
def test_same_batch_retry_does_not_recount_or_recreate_records(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.URL,
        payload={"source_url": "https://e.test/1", "original_text": "Need gear"},
        key="retry-url",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)
    kwargs = {
        "batch_id": batch.id,
        "organization": organization,
        "claim_token": claimed.claim_token,
    }

    first = IngestionService.run(**kwargs)
    second = IngestionService.run(**kwargs)

    assert first.id == second.id
    assert (
        second.received_count,
        second.accepted_count,
        second.duplicate_count,
        second.failed_count,
    ) == (1, 1, 0, 0)
    assert IngestionRow.objects.count() == 1
    assert SourceContent.objects.count() == 1
    assert SourceSignal.objects.count() == 1
    assert SourceEvidence.objects.count() == 1


@pytest.mark.django_db
def test_json_text_payload_ingests_without_assuming_an_inline_asset_reference(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload=(
            '{"rows":[{"source_url":"https://e.test/text-json",'
            '"original_text":"Need gear"}]}'
        ),
        key="json-text",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.SUCCEEDED
    assert result.accepted_count == 1


@pytest.mark.django_db
def test_second_identical_row_is_a_duplicate_without_new_domain_records(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "rows": [
                {"source_url": "https://e.test/1", "original_text": "Need gear"},
                {"source_url": "https://e.test/1", "original_text": "Need  gear"},
            ]
        },
        key="duplicate-json",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert (result.accepted_count, result.duplicate_count, result.failed_count) == (1, 1, 0)
    assert list(result.rows.values_list("outcome", flat=True)) == [
        IngestionRow.Outcome.ACCEPTED,
        IngestionRow.Outcome.DUPLICATE,
    ]
    assert SourceContent.objects.count() == 1
    assert SourceSignal.objects.count() == 1
    assert SourceEvidence.objects.count() == 1


@pytest.mark.django_db
def test_stale_token_cannot_change_batch_rows_or_evidence(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.URL,
        payload={"source_url": "https://e.test/1", "original_text": "Need gear"},
        key="stale-token",
        user=user,
    )
    JobService.claim(worker_id="test-worker", job_id=job.id)

    with pytest.raises(StaleJobWorkerError):
        IngestionService.run(
            batch_id=batch.id,
            organization=organization,
            claim_token=uuid4(),
        )

    batch.refresh_from_db()
    assert batch.status == IngestionBatch.Status.QUEUED
    assert batch.rows.count() == 0
    assert SourceContent.objects.count() == 0
    assert SourceSignal.objects.count() == 0
    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_batch_organization_mismatch_is_rejected_before_any_write(
    organization, other_organization, job, user
):
    batch = make_batch(
        organization=organization,
        job=job,
        source_type=IngestionBatch.SourceType.URL,
        payload={"source_url": "https://e.test/1", "original_text": "Need gear"},
        key="wrong-org",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    with pytest.raises(IngestionBatch.DoesNotExist):
        IngestionService.run(
            batch_id=batch.id,
            organization=other_organization,
            claim_token=claimed.claim_token,
        )

    assert IngestionRow.objects.count() == 0


@pytest.mark.django_db
def test_cross_organization_screenshot_asset_becomes_a_failed_row(
    organization, job, user, target, other_asset
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        payload={
            "source_url": "https://e.test/shot",
            "original_text": "Need gear",
            "screenshot_asset_id": str(other_asset.id),
        },
        key="cross-org-shot",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.FAILED
    assert (result.received_count, result.accepted_count, result.failed_count) == (1, 0, 1)
    row = result.rows.get()
    assert row.outcome == IngestionRow.Outcome.FAILED
    assert row.error["code"] == "SCREENSHOT_ASSET_UNAVAILABLE"
    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_row_savepoint_preserves_owned_asset_neighbor_when_another_asset_is_rejected(
    organization, job, user, target, asset, other_asset
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.CSV,
        payload={
            "text": (
                "source_url,original_text,screenshot_asset_id\n"
                f"https://e.test/owned,Need gear,{asset.id}\n"
                f"https://e.test/other,Need shaft,{other_asset.id}"
            )
        },
        key="asset-savepoints",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.PARTIAL_SUCCESS
    assert (result.accepted_count, result.failed_count) == (1, 1)
    accepted, failed = result.rows.all()
    assert accepted.source_evidence.screenshot_asset_id == asset.id
    assert failed.error["code"] == "SCREENSHOT_ASSET_UNAVAILABLE"
    assert SourceContent.objects.count() == 1
    assert SourceSignal.objects.count() == 1
    assert SourceEvidence.objects.count() == 1


@pytest.mark.django_db
def test_cross_organization_import_asset_is_rejected_for_every_import_row(
    organization, job, user, target, other_asset
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(other_asset.id),
            "rows": [{"source_url": "https://e.test/import", "original_text": "Need gear"}],
        },
        key="cross-org-import-asset",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.FAILED
    assert result.rows.get().error["code"] == "IMPORT_ASSET_UNAVAILABLE"
    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_import_asset_archived_after_batch_creation_is_rejected_by_worker(
    organization, job, user, target, asset
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(asset.id),
            "rows": [
                {"source_url": "https://e.test/archived", "original_text": "Need gear"}
            ],
        },
        key="archived-import-asset",
        user=user,
    )
    asset.status = MaterialAsset.Status.ARCHIVED
    asset.save(update_fields=["status", "updated_at"])
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.FAILED
    assert result.rows.get().error["code"] == "IMPORT_ASSET_UNAVAILABLE"
    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_batch_level_row_limit_failure_is_persisted_without_rows(
    organization, job, user
):
    batch = make_batch(
        organization=organization,
        job=job,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "rows": [
                {"source_url": f"https://e.test/{index}", "original_text": "Need gear"}
                for index in range(10_001)
            ]
        },
        key="too-many",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.FAILED
    assert result.received_count == 0
    assert result.rows.count() == 0
    assert result.row_errors[0]["code"] == "BATCH_ROW_LIMIT_EXCEEDED"


@pytest.mark.django_db
def test_integrity_error_isolated_to_middle_row_and_retry_uses_persisted_outcomes(
    organization, job, user, target, monkeypatch
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "rows": [
                {"source_url": "https://e.test/first", "original_text": "First"},
                {"source_url": "https://e.test/middle", "original_text": "Middle"},
                {"source_url": "https://e.test/third", "original_text": "Third"},
            ]
        },
        key="integrity-savepoint",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)
    original = IngestionService._persist_valid_row

    def fail_middle(*, batch, organization, row):
        if row.source_url.endswith("/middle"):
            raise IntegrityError("simulated row constraint")
        return original(batch=batch, organization=organization, row=row)

    monkeypatch.setattr(IngestionService, "_persist_valid_row", fail_middle)
    kwargs = {
        "batch_id": batch.id,
        "organization": organization,
        "claim_token": claimed.claim_token,
    }

    first = IngestionService.run(**kwargs)
    second = IngestionService.run(**kwargs)

    assert first.id == second.id
    assert second.status == IngestionBatch.Status.PARTIAL_SUCCESS
    assert (
        second.received_count,
        second.accepted_count,
        second.duplicate_count,
        second.failed_count,
    ) == (3, 2, 0, 1)
    assert list(second.rows.values_list("row_number", "outcome")) == [
        (1, IngestionRow.Outcome.ACCEPTED),
        (2, IngestionRow.Outcome.FAILED),
        (3, IngestionRow.Outcome.ACCEPTED),
    ]
    assert second.rows.get(row_number=2).error == {
        "row": 2,
        "code": "ROW_DATABASE_CONFLICT",
        "recovery_action": "Review this row's values and retry the import.",
    }
    assert SourceContent.objects.count() == 2
    assert SourceSignal.objects.count() == 2
    assert SourceEvidence.objects.count() == 2


@pytest.mark.django_db
def test_connection_database_error_propagates_instead_of_becoming_a_row_failure(
    organization, job, user, target, monkeypatch
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.URL,
        payload={"source_url": "https://e.test/connection", "original_text": "Public"},
        key="connection-error",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    def fail_connection(**_kwargs):
        raise InterfaceError("simulated lost connection")

    monkeypatch.setattr(IngestionService, "_persist_valid_row", fail_connection)

    with pytest.raises(InterfaceError, match="lost connection"):
        IngestionService.run(
            batch_id=batch.id,
            organization=organization,
            claim_token=claimed.claim_token,
        )

    batch.refresh_from_db()
    assert batch.status == IngestionBatch.Status.QUEUED
    assert batch.rows.count() == 0


@pytest.mark.django_db
def test_correct_paste_type_succeeds_with_matching_evidence_provenance(
    organization, job, user, target
):
    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.PASTE,
        payload={"text": "https://e.test/paste\tNeed gear"},
        key="paste-provenance",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    evidence = result.rows.get().source_evidence
    assert result.status == IngestionBatch.Status.SUCCEEDED
    assert evidence.collection_method == SourceEvidence.CollectionMethod.PASTE
    assert evidence.evidence_type == SourceEvidence.EvidenceType.PUBLIC_TEXT


@pytest.mark.django_db
@pytest.mark.parametrize("relabelled_type", ["URL", "CSV", "JSON"])
def test_ingestion_rejects_database_relabelled_prepared_reference(
    organization, job, user, target, relabelled_type
):
    from django.db import connection

    batch = make_batch(
        organization=organization,
        job=job,
        target=target,
        source_type=IngestionBatch.SourceType.PASTE,
        payload={"text": "https://e.test/paste\tNeed gear"},
        key=f"relabel-{relabelled_type}",
        user=user,
    )
    claimed = JobService.claim(worker_id="test-worker", job_id=job.id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET source_type = %s WHERE id = %s",
            [relabelled_type, batch.id.hex],
        )

    with pytest.raises(ValidationError, match="source type"):
        IngestionService.run(
            batch_id=batch.id,
            organization=organization,
            claim_token=claimed.claim_token,
        )

    batch.refresh_from_db()
    assert batch.status == IngestionBatch.Status.QUEUED
    assert batch.rows.count() == 0
    assert SourceEvidence.objects.count() == 0
