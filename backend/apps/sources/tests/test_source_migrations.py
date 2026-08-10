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
