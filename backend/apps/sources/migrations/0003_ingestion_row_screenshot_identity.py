from uuid import UUID

from django.db import migrations, models


def _uuid(value):
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def backfill_screenshot_identity(apps, schema_editor):
    row_model = apps.get_model("sources", "IngestionRow")
    for row in (
        row_model.objects.select_related("batch__job", "source_evidence")
        .order_by("pk")
        .iterator()
    ):
        normalized = row.normalized_input if isinstance(row.normalized_input, dict) else {}
        asset_id = _uuid(normalized.get("screenshot_asset_id"))
        if asset_id is None and row.source_evidence_id:
            asset_id = row.source_evidence.screenshot_asset_id
        if asset_id is None and isinstance(row.batch.input_reference, dict):
            for prepared_row in row.batch.input_reference.get("rows", []):
                if (
                    isinstance(prepared_row, dict)
                    and prepared_row.get("row_number") == row.row_number
                ):
                    asset_id = _uuid(prepared_row.get("screenshot_asset_id"))
                    break
        if asset_id is None and row.batch.job_id:
            snapshot = row.batch.job.input_snapshot
            if isinstance(snapshot, dict):
                snapshot_reference = snapshot.get("input_reference")
                if not isinstance(snapshot_reference, dict):
                    snapshot_reference = snapshot.get("prepared_reference")
                if not isinstance(snapshot_reference, dict) and isinstance(
                    snapshot.get("rows"), list
                ):
                    snapshot_reference = snapshot
                if isinstance(snapshot_reference, dict):
                    for prepared_row in snapshot_reference.get("rows", []):
                        if (
                            isinstance(prepared_row, dict)
                            and prepared_row.get("row_number") == row.row_number
                        ):
                            asset_id = _uuid(
                                prepared_row.get("screenshot_asset_id")
                            )
                            break
        tombstoned = isinstance(normalized.get("retention"), dict)
        unproven = bool(
            asset_id is None
            and tombstoned
            and row.batch.source_type == "SCREENSHOT"
        )
        row_model.objects.filter(pk=row.pk).update(
            request_screenshot_asset_id=asset_id,
            request_screenshot_identity_unproven=unproven,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("sources", "0002_ingestion_request_identity")]

    operations = [
        migrations.AddField(
            model_name="ingestionrow",
            name="request_screenshot_asset_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="ingestionrow",
            name="request_screenshot_identity_unproven",
            field=models.BooleanField(
                db_index=True,
                default=False,
                editable=False,
            ),
        ),
        migrations.RunPython(backfill_screenshot_identity, noop_reverse),
    ]
