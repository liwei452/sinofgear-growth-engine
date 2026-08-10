import hashlib
import json
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor


def _digest(reference):
    return hashlib.sha256(
        json.dumps(reference, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


@pytest.mark.django_db(transaction=True)
def test_request_identity_migration_backfills_plain_and_already_retained_batches():
    before = ("sources", "0001_initial")
    after = ("sources", "0002_ingestion_request_identity")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([before])
        old_apps = executor.loader.project_state([before]).apps
        organization_model = old_apps.get_model("identity", "Organization")
        job_model = old_apps.get_model("jobs", "Job")
        batch_model = old_apps.get_model("sources", "IngestionBatch")
        organization = organization_model.objects.create(
            name="Source identity migration",
            slug="source-identity-migration",
        )
        plain_reference = {
            "schema": "GUIDED_IMPORT_V1",
            "source_type": "URL",
            "rows": [],
            "errors": [],
        }
        plain = batch_model.objects.create(
            organization=organization,
            source_type="URL",
            input_reference=plain_reference,
            idempotency_key="migration-plain",
        )
        original_digest = "a" * 64
        original_asset_id = uuid4()
        job = job_model.objects.create(
            organization=organization,
            type="SOURCE_IMPORT",
            input_snapshot={
                "prepared_reference_sha256": original_digest,
                "import_asset_id": str(original_asset_id),
            },
            idempotency_key="migration-retained",
        )
        retained = batch_model.objects.create(
            organization=organization,
            source_type="SCREENSHOT",
            input_reference={
                "schema": "GUIDED_IMPORT_V1",
                "source_type": "SCREENSHOT",
                "rows": [],
                "errors": [],
                "retention": {
                    "reason": "TRANSIENT_30D_EXPIRED",
                },
            },
            idempotency_key="migration-retained",
            job=job,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        migrated_model = executor.loader.project_state([after]).apps.get_model(
            "sources", "IngestionBatch"
        )

        migrated_plain = migrated_model.objects.get(pk=plain.pk)
        migrated_retained = migrated_model.objects.get(pk=retained.pk)
        assert migrated_plain.prepared_reference_sha256 == _digest(
            plain_reference
        )
        assert migrated_plain.request_import_asset_id is None
        assert migrated_retained.prepared_reference_sha256 == original_digest
        assert migrated_retained.request_import_asset_id == original_asset_id
        assert migrated_retained.input_reference == {
            "schema": "GUIDED_IMPORT_V1",
            "source_type": "SCREENSHOT",
            "rows": [],
            "errors": [],
        }
        with pytest.raises(IntegrityError), transaction.atomic():
            migrated_model.objects.filter(pk=plain.pk).update(
                prepared_reference_sha256=""
            )
    finally:
        MigrationExecutor(connection).migrate(latest)


@pytest.mark.django_db(transaction=True)
def test_screenshot_identity_migration_backfills_and_fails_closed():
    before = ("sources", "0002_ingestion_request_identity")
    after = ("sources", "0003_ingestion_row_screenshot_identity")
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    screenshot_id = uuid4()
    snapshot_screenshot_id = uuid4()

    try:
        executor.migrate([before])
        old_apps = executor.loader.project_state([before]).apps
        organization_model = old_apps.get_model("identity", "Organization")
        batch_model = old_apps.get_model("sources", "IngestionBatch")
        row_model = old_apps.get_model("sources", "IngestionRow")
        job_model = old_apps.get_model("jobs", "Job")
        organization = organization_model.objects.create(
            name="Screenshot identity migration",
            slug="screenshot-identity-migration",
        )
        proven_batch = batch_model.objects.create(
            organization=organization,
            source_type="JSON",
            input_reference={"rows": []},
            idempotency_key="migration-proven-screenshot",
            prepared_reference_sha256="a" * 64,
        )
        proven = row_model.objects.create(
            organization=organization,
            batch=proven_batch,
            row_number=1,
            normalized_input={"screenshot_asset_id": str(screenshot_id)},
            outcome="FAILED",
        )
        unknown_batch = batch_model.objects.create(
            organization=organization,
            source_type="SCREENSHOT",
            input_reference={"rows": []},
            idempotency_key="migration-unknown-screenshot",
            prepared_reference_sha256="b" * 64,
        )
        unknown = row_model.objects.create(
            organization=organization,
            batch=unknown_batch,
            row_number=1,
            normalized_input={
                "screenshot_asset_id": None,
                "retention": {"status": "REDACTED_BY_RETENTION"},
            },
            outcome="DUPLICATE",
        )
        unknown_json_batch = batch_model.objects.create(
            organization=organization,
            source_type="JSON",
            input_reference={"rows": []},
            idempotency_key="migration-unknown-json-screenshot",
            prepared_reference_sha256="d" * 64,
        )
        unknown_json = row_model.objects.create(
            organization=organization,
            batch=unknown_json_batch,
            row_number=1,
            normalized_input={
                "screenshot_asset_id": None,
                "retention": {"status": "REDACTED_BY_RETENTION"},
            },
            outcome="DUPLICATE",
        )
        unknown_csv_batch = batch_model.objects.create(
            organization=organization,
            source_type="CSV",
            input_reference={"rows": []},
            idempotency_key="migration-unknown-csv-screenshot",
            prepared_reference_sha256="e" * 64,
        )
        unknown_csv = row_model.objects.create(
            organization=organization,
            batch=unknown_csv_batch,
            row_number=1,
            normalized_input={
                "screenshot_asset_id": None,
                "retention": {"status": "REDACTED_BY_RETENTION"},
            },
            outcome="DUPLICATE",
        )
        known_no_screenshot_batch = batch_model.objects.create(
            organization=organization,
            source_type="JSON",
            input_reference={"rows": []},
            idempotency_key="migration-known-no-screenshot",
            prepared_reference_sha256="f" * 64,
        )
        known_no_screenshot = row_model.objects.create(
            organization=organization,
            batch=known_no_screenshot_batch,
            row_number=1,
            normalized_input={"screenshot_asset_id": None},
            outcome="FAILED",
        )
        snapshot_job = job_model.objects.create(
            organization=organization,
            type="SOURCE_IMPORT",
            input_snapshot={
                "input_reference": {
                    "rows": [
                        {
                            "row_number": 1,
                            "screenshot_asset_id": str(snapshot_screenshot_id),
                        }
                    ]
                }
            },
            idempotency_key="migration-snapshot-screenshot",
        )
        snapshot_batch = batch_model.objects.create(
            organization=organization,
            source_type="SCREENSHOT",
            input_reference={"rows": []},
            idempotency_key="migration-snapshot-screenshot",
            prepared_reference_sha256="c" * 64,
            job=snapshot_job,
        )
        snapshot_row = row_model.objects.create(
            organization=organization,
            batch=snapshot_batch,
            row_number=1,
            normalized_input={
                "screenshot_asset_id": None,
                "retention": {"status": "REDACTED_BY_RETENTION"},
            },
            outcome="DUPLICATE",
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        migrated = executor.loader.project_state([after]).apps.get_model(
            "sources", "IngestionRow"
        )

        proven = migrated.objects.get(pk=proven.pk)
        unknown = migrated.objects.get(pk=unknown.pk)
        unknown_json = migrated.objects.get(pk=unknown_json.pk)
        unknown_csv = migrated.objects.get(pk=unknown_csv.pk)
        known_no_screenshot = migrated.objects.get(pk=known_no_screenshot.pk)
        snapshot_row = migrated.objects.get(pk=snapshot_row.pk)
        assert proven.request_screenshot_asset_id == screenshot_id
        assert not proven.request_screenshot_identity_unproven
        assert unknown.request_screenshot_asset_id is None
        assert unknown.request_screenshot_identity_unproven
        assert unknown_json.request_screenshot_asset_id is None
        assert unknown_json.request_screenshot_identity_unproven
        assert unknown_csv.request_screenshot_asset_id is None
        assert unknown_csv.request_screenshot_identity_unproven
        assert known_no_screenshot.request_screenshot_asset_id is None
        assert not known_no_screenshot.request_screenshot_identity_unproven
        assert snapshot_row.request_screenshot_asset_id == snapshot_screenshot_id
        assert not snapshot_row.request_screenshot_identity_unproven
    finally:
        MigrationExecutor(connection).migrate(latest)
