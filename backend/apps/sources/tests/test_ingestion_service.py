from uuid import uuid4
from dataclasses import FrozenInstanceError

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, InterfaceError, connection, transaction
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext

from apps.assets.models import MaterialAsset
from apps.identity.models import Organization
from apps.jobs.services import JobService, StaleJobWorkerError
from apps.sources.importers import prepare_import_reference
from apps.sources.models import (
    IngestionBatch,
    IngestionRow,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from apps.sources.services import (
    EvidenceService,
    IngestionService,
    source_import_job_snapshot,
)


def make_batch(*, organization, job, source_type, payload, key, user, target=None):
    input_reference = prepare_import_reference(payload, source_type=source_type)
    batch = IngestionBatch.objects.create(
        organization=organization,
        monitoring_target=target,
        source_type=source_type,
        input_reference=input_reference,
        idempotency_key=key,
        created_by=user,
    )
    bound_job = JobService.create(
        organization=organization,
        job_type="SOURCE_IMPORT",
        input_snapshot=source_import_job_snapshot(batch),
        idempotency_key=key,
        created_by=user,
    )
    batch.job = bound_job
    batch.save(update_fields=["job", "updated_at"])
    return batch


def assert_preflight_failure(result):
    assert result.status == IngestionBatch.Status.FAILED
    assert result.started_at is None
    assert result.received_count == 0
    assert result.rows.count() == 0
    assert result.row_errors == [
        {
            "row": None,
            "code": "SOURCE_IMPORT_PREFLIGHT_FAILED",
            "recovery_action": "Review the source import configuration and retry.",
        }
    ]
    assert SourceEvidence.objects.count() == 0


def _run_asset_backed_batch_with_query_count(
    *, organization, user, target, import_asset, screenshot_assets, key
):
    batch = make_batch(
        organization=organization,
        job=None,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": f"https://e.test/{key}/{index}",
                    "original_text": f"Need gear {index}",
                    "screenshot_asset_id": str(screenshot_asset.id),
                }
                for index, screenshot_asset in enumerate(screenshot_assets)
            ],
        },
        key=key,
        user=user,
    )
    claimed = JobService.claim(worker_id=f"worker-{key}", job_id=batch.job_id)
    with CaptureQueriesContext(connection) as queries:
        result = IngestionService.run(
            batch_id=batch.id,
            organization=organization,
            claim_token=claimed.claim_token,
        )
    asset_queries = [
        query["sql"]
        for query in queries.captured_queries
        if "assets_materialasset" in query["sql"].lower()
    ]
    assert result.status == IngestionBatch.Status.SUCCEEDED
    assert result.accepted_count == len(screenshot_assets)
    assert set(
        SourceEvidence.objects.filter(source_url__contains=f"/{key}/").values_list(
            "screenshot_asset_id", "import_asset_id"
        )
    ) == {
        (screenshot_asset.id, import_asset.id)
        for screenshot_asset in screenshot_assets
    }
    return asset_queries


@pytest.mark.django_db
def test_locked_asset_query_count_is_constant_for_one_or_many_rows(
    organization, user, target, asset
):
    screenshot_assets = []
    for index in range(8):
        asset_id = uuid4()
        screenshot_assets.append(
            MaterialAsset.objects.create(
                id=asset_id,
                organization=organization,
                asset_type=MaterialAsset.AssetType.IMAGE,
                storage_key=(
                    f"organizations/{organization.id}/assets/{asset_id}/original"
                ),
                original_filename=f"query-bound-{index}.png",
                mime_type="image/png",
                size_bytes=1,
                checksum=f"{index + 1:064x}",
                created_by=user,
            )
        )
    one_row_queries = _run_asset_backed_batch_with_query_count(
        organization=organization,
        user=user,
        target=target,
        import_asset=asset,
        screenshot_assets=[screenshot_assets[0]],
        key="one-locked-asset-row",
    )
    many_row_queries = _run_asset_backed_batch_with_query_count(
        organization=organization,
        user=user,
        target=target,
        import_asset=asset,
        screenshot_assets=screenshot_assets,
        key="many-locked-asset-rows",
    )

    assert len(one_row_queries) == len(many_row_queries) == 1


@pytest.mark.django_db
def test_trusted_locked_asset_evidence_path_rejects_non_ingestion_callers(
    organization, user, target, asset, signal
):
    batch = make_batch(
        organization=organization,
        job=None,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(asset.id),
            "rows": [
                {
                    "source_url": "https://e.test/trusted-boundary",
                    "original_text": "Need gear",
                    "screenshot_asset_id": str(asset.id),
                }
            ],
        },
        key="trusted-asset-boundary",
        user=user,
    )
    with transaction.atomic():
        locked_batch = IngestionBatch.objects.select_for_update().get(pk=batch.pk)
        resources, error = IngestionService._preflight_resources(
            batch=locked_batch,
            job=batch.job,
            organization=organization,
        )
        assert error is None

        with pytest.raises(ValidationError, match="trusted locked asset"):
            EvidenceService._create_from_locked_ingestion_assets(
                resources=resources,
                screenshot_asset_id=str(asset.id),
                organization=organization,
                signal=signal,
                original_text="Need gear",
                source_url="https://e.test/trusted-boundary",
                platform="MANUAL",
                collection_method=IngestionBatch.SourceType.JSON,
                public_published_at=None,
                created_by=user,
            )

    assert SourceEvidence.objects.count() == 0


@pytest.mark.django_db
def test_preflight_acquires_target_and_complete_asset_locks_inside_transaction(
    organization, user, target, asset, monkeypatch
):
    batch = make_batch(
        organization=organization,
        job=None,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(asset.id),
            "rows": [
                {
                    "source_url": f"https://e.test/lock/{index}",
                    "original_text": f"Need gear {index}",
                    "screenshot_asset_id": str(asset.id),
                }
                for index in range(4)
            ],
        },
        key="locked-resource-transaction",
        user=user,
    )
    claimed = JobService.claim(worker_id="lock-worker", job_id=batch.job_id)
    original_asset_lock = MaterialAsset.objects.select_for_update
    original_target_lock = MonitoringTarget.objects.select_for_update
    lock_calls = {"assets": 0, "targets": 0}

    def lock_assets(*args, **kwargs):
        assert connection.in_atomic_block
        lock_calls["assets"] += 1
        return original_asset_lock(*args, **kwargs)

    def lock_target(*args, **kwargs):
        assert connection.in_atomic_block
        lock_calls["targets"] += 1
        return original_target_lock(*args, **kwargs)

    monkeypatch.setattr(MaterialAsset.objects, "select_for_update", lock_assets)
    monkeypatch.setattr(MonitoringTarget.objects, "select_for_update", lock_target)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.SUCCEEDED
    assert lock_calls == {"assets": 1, "targets": 1}


@pytest.mark.django_db
def test_asset_backed_import_locks_organization_asset_then_batch(
    organization, user, target, asset, monkeypatch
):
    batch = make_batch(
        organization=organization,
        job=None,
        target=target,
        source_type=IngestionBatch.SourceType.JSON,
        payload={
            "import_asset_id": str(asset.id),
            "rows": [
                {
                    "source_url": "https://e.test/import-lock-order",
                    "original_text": "Need gear",
                }
            ],
        },
        key="asset-backed-import-lock-order",
        user=user,
    )
    claimed = JobService.claim(worker_id="asset-lock-worker", job_id=batch.job_id)
    locked_models = []
    original_fetch_all = QuerySet._fetch_all

    def observe_locked_fetch(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        return original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", observe_locked_fetch)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert result.status == IngestionBatch.Status.SUCCEEDED
    first_positions = {
        model: locked_models.index(model)
        for model in (Organization, MaterialAsset, IngestionBatch)
    }
    assert first_positions[Organization] < first_positions[MaterialAsset]
    assert first_positions[MaterialAsset] < first_positions[IngestionBatch]


@pytest.mark.django_db
def test_locked_resource_cache_is_read_only_and_rejects_object_state_drift(
    organization, user, target, asset
):
    batch = make_batch(
        organization=organization,
        job=None,
        target=target,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        payload={
            "source_url": "https://e.test/cache-drift",
            "original_text": "Need gear",
            "screenshot_asset_id": str(asset.id),
        },
        key="locked-resource-cache",
        user=user,
    )
    with transaction.atomic():
        locked_batch = IngestionBatch.objects.select_for_update().get(pk=batch.pk)
        resources, error = IngestionService._preflight_resources(
            batch=locked_batch,
            job=batch.job,
            organization=organization,
        )
        assert error is None
        locked_asset = resources.assets[str(asset.id)]

        with pytest.raises(TypeError):
            resources.assets[str(asset.id)] = locked_asset
        with pytest.raises(FrozenInstanceError):
            locked_asset.status = MaterialAsset.Status.ARCHIVED

        locked_asset._instance.status = MaterialAsset.Status.ARCHIVED
        with pytest.raises(ValidationError, match="unavailable"):
            resources.screenshot_asset(asset.id, organization=organization)

    assert SourceEvidence.objects.count() == 0


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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)
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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

    with pytest.raises(IngestionBatch.DoesNotExist):
        IngestionService.run(
            batch_id=batch.id,
            organization=other_organization,
            claim_token=claimed.claim_token,
        )

    assert IngestionRow.objects.count() == 0


@pytest.mark.django_db
def test_cross_organization_screenshot_asset_fails_preflight_without_rows(
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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert_preflight_failure(result)


@pytest.mark.django_db
def test_preflight_rejects_all_rows_when_any_screenshot_asset_is_foreign(
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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert_preflight_failure(result)
    assert SourceContent.objects.count() == 0
    assert SourceSignal.objects.count() == 0


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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert_preflight_failure(result)


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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    assert_preflight_failure(result)


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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)
    original = IngestionService._persist_valid_row

    def fail_middle(*, batch, organization, row, resources):
        if row.source_url.endswith("/middle"):
            raise IntegrityError("simulated row constraint")
        return original(
            batch=batch,
            organization=organization,
            row=row,
            resources=resources,
        )

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)

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
    claimed = JobService.claim(worker_id="test-worker", job_id=batch.job_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionbatch SET source_type = %s WHERE id = %s",
            [relabelled_type, batch.id.hex],
        )

    result = IngestionService.run(
        batch_id=batch.id,
        organization=organization,
        claim_token=claimed.claim_token,
    )

    batch.refresh_from_db()
    assert_preflight_failure(result)
