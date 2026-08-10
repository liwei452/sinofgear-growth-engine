import json
from contextlib import nullcontext
from copy import deepcopy

import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.sources.models import (
    IngestionBatch,
    IngestionRow,
    SourceEvidence,
    evidence_service_writes,
    ingestion_row_service_writes,
)
from apps.sources.importers import prepare_import_reference
from apps.sources.services import EvidenceService


def _write_context(instance):
    if isinstance(instance, SourceEvidence):
        return evidence_service_writes()
    if isinstance(instance, IngestionRow):
        return ingestion_row_service_writes()
    return nullcontext()


def _empty_reference(source_type="PASTE"):
    payload = {"text": ""} if source_type in {"CSV", "PASTE"} else {"rows": []}
    return prepare_import_reference(payload, source_type=source_type)


@pytest.mark.django_db
def test_persisted_source_organization_is_immutable_through_every_orm_path(
    organization, other_organization, target, content, signal, user
):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=_empty_reference(),
        idempotency_key="organization-immutable-batch",
        monitoring_target=target,
    )
    evidence = EvidenceService.create(
        organization=organization,
        signal=signal,
        original_text="Public organization fact",
        source_url="https://example.com/organization-fact",
        platform="MANUAL",
        collection_method="PASTE",
        public_published_at=None,
        created_by=user,
    )
    row = IngestionRow(
        organization=organization,
        batch=batch,
        row_number=1,
        normalized_input={"text": "public"},
        outcome=IngestionRow.Outcome.ACCEPTED,
        source_content=content,
        source_signal=signal,
        source_evidence=evidence,
    )
    with ingestion_row_service_writes():
        row.save()

    for source_object in (target, batch, content, signal, evidence, row):
        model = type(source_object)
        accessor = model._meta.get_field("organization").remote_field.get_accessor_name()

        instance = model.objects.get(pk=source_object.pk)
        instance.organization = other_organization
        with _write_context(instance), pytest.raises(ValidationError, match="immutable"):
            instance.save()

        instance = model.objects.get(pk=source_object.pk)
        with _write_context(instance), pytest.raises(ValidationError, match="immutable"):
            model.objects.filter(pk=instance.pk).update(organization=other_organization)

        instance = model.objects.get(pk=source_object.pk)
        instance.organization = other_organization
        with _write_context(instance), pytest.raises(ValidationError, match="immutable"):
            model.objects.bulk_update([instance], ["organization"])

        persisted = model.objects.get(pk=source_object.pk)
        assert persisted.organization_id == organization.id
        assert getattr(organization, accessor).filter(pk=source_object.pk).exists()
        assert not getattr(other_organization, accessor).filter(pk=source_object.pk).exists()


@pytest.mark.django_db
def test_evidence_service_requires_active_organization_and_hides_cross_org_signal(
    other_organization, signal, user
):
    with pytest.raises(ValidationError) as exc_info:
        EvidenceService.create(
            organization=other_organization,
            signal=signal,
            original_text="Cross organization fact",
            source_url="https://example.com/cross-org",
            platform="MANUAL",
            collection_method="PASTE",
            public_published_at=None,
            created_by=user,
        )
    message = str(exc_info.value)
    assert "unavailable for this organization" in message
    assert str(signal.pk) not in message


@pytest.mark.django_db
@pytest.mark.parametrize("delete_style", ["instance", "queryset"])
def test_ingestion_batch_with_rows_cannot_be_deleted(
    organization, delete_style
):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=_empty_reference(),
        idempotency_key=f"protected-batch-{delete_style}",
    )
    row = IngestionRow(
        organization=organization,
        batch=batch,
        row_number=1,
        normalized_input={"text": "public"},
        outcome=IngestionRow.Outcome.ACCEPTED,
    )
    with ingestion_row_service_writes():
        row.save()

    with pytest.raises(ProtectedError):
        if delete_style == "instance":
            batch.delete()
        else:
            IngestionBatch.objects.filter(pk=batch.pk).delete()
    assert IngestionBatch.objects.filter(pk=batch.pk).exists()
    assert IngestionRow.objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_ingestion_batch_history_cannot_be_deleted_even_before_rows(organization):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.URL,
        input_reference=prepare_import_reference(
            {"source_url": "https://e.test/empty", "original_text": "Public"},
            source_type="URL",
        ),
        idempotency_key="protected-empty-batch",
    )
    with pytest.raises(ProtectedError):
        IngestionBatch.objects.filter(pk=batch.pk).delete()
    assert IngestionBatch.objects.filter(pk=batch.pk).exists()


@pytest.mark.django_db
def test_all_source_json_fields_sanitize_nested_secrets_without_mutating_input(
    organization, target
):
    sensitive = {
        "captcha": "solved-value",
        "nested": [
            {
                "verification_code": "123456",
                "cookie": "session=private",
                "access_token": "private-token",
                "keep": "public",
            }
        ],
    }
    original = deepcopy(sensitive)
    clean = {"nested": [{"keep": "public"}]}

    target.schedule = sensitive
    target.capability_snapshot = sensitive
    MonitoringTarget = type(target)
    MonitoringTarget.objects.bulk_update(
        [target], ["schedule", "capability_snapshot"]
    )
    target.refresh_from_db()
    assert target.schedule == clean
    assert target.capability_snapshot == clean

    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.API,
        idempotency_key="sanitized-all-json",
        input_reference=sensitive,
        row_errors=sensitive,
    )
    assert batch.input_reference == clean
    assert batch.row_errors == clean

    batch.input_reference = sensitive
    batch.row_errors = sensitive
    IngestionBatch.objects.bulk_update(
        [batch], ["input_reference", "row_errors"]
    )
    batch.refresh_from_db()
    assert batch.input_reference == clean
    assert batch.row_errors == clean

    row = IngestionRow(
        organization=organization,
        batch=batch,
        row_number=1,
        normalized_input=sensitive,
        error=sensitive,
        outcome=IngestionRow.Outcome.FAILED,
    )
    with ingestion_row_service_writes():
        IngestionRow.objects.bulk_create([row])
    row.refresh_from_db()
    assert row.normalized_input == clean
    assert row.error == clean

    row.normalized_input = sensitive
    row.error = sensitive
    with ingestion_row_service_writes():
        IngestionRow.objects.bulk_update(
            [row], ["normalized_input", "error"]
        )
    row.refresh_from_db()
    assert row.normalized_input == clean
    assert row.error == clean
    assert sensitive == original


@pytest.mark.django_db
@pytest.mark.parametrize("raw_reference", ["raw source text", b"raw source bytes"])
@pytest.mark.parametrize(
    "source_type", [IngestionBatch.SourceType.PASTE, IngestionBatch.SourceType.API]
)
def test_guided_batch_rejects_raw_text_on_create_and_bulk_create(
    organization, raw_reference, source_type
):
    values = {
        "organization": organization,
        "source_type": source_type,
        "input_reference": raw_reference,
    }
    with pytest.raises(ValidationError, match="prepared"):
        IngestionBatch.objects.create(
            idempotency_key=f"raw-create-{source_type}-{type(raw_reference).__name__}",
            **values,
        )
    with pytest.raises(ValidationError, match="prepared"):
        IngestionBatch.objects.bulk_create(
            [
                IngestionBatch(
                    idempotency_key=f"raw-bulk-{source_type}-{type(raw_reference).__name__}",
                    **values,
                )
            ]
        )


@pytest.mark.django_db
def test_guided_batch_rejects_raw_text_on_save_update_and_bulk_update(organization):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=_empty_reference(),
        idempotency_key="safe-before-raw-write",
    )

    batch.input_reference = "raw save text"
    with pytest.raises(ValidationError, match="prepared"):
        batch.save()
    with pytest.raises(ValidationError, match="prepared"):
        IngestionBatch.objects.filter(pk=batch.pk).update(input_reference="raw update text")
    batch.refresh_from_db()
    batch.input_reference = "raw bulk update text"
    with pytest.raises(ValidationError, match="prepared"):
        IngestionBatch.objects.bulk_update([batch], ["input_reference"])


@pytest.mark.django_db
def test_only_prepared_rows_persist_and_legitimate_cookie_word_is_unchanged(organization):
    raw_document = json.dumps(
        {
            "rows": [
                {
                    "source_url": "https://e.test/public",
                    "original_text": "Customer asks about cookie dimensions.",
                    "cookie": "session=private",
                    "authorization": "Bearer private",
                    "raw_headers": {"X-Secret": "private"},
                }
            ]
        }
    )
    reference = prepare_import_reference(raw_document, source_type="JSON")
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.JSON,
        input_reference=reference,
        idempotency_key="prepared-only",
    )
    batch.refresh_from_db()

    persisted = json.dumps(batch.input_reference, sort_keys=True)
    assert batch.input_reference["rows"][0]["original_text"] == (
        "Customer asks about cookie dimensions."
    )
    assert raw_document not in persisted
    assert "session=private" not in persisted
    assert "Bearer private" not in persisted
    assert "X-Secret" not in persisted


@pytest.mark.django_db
def test_prepared_shape_cannot_smuggle_raw_text_through_error_or_typed_fields(organization):
    reference = prepare_import_reference(
        {"source_url": "https://e.test/public", "original_text": "Public"},
        source_type="URL",
    )
    reference["errors"] = [
        {
            "row": None,
            "code": "INVALID_PAYLOAD",
            "recovery_action": "authorization=Bearer private",
        }
    ]
    reference["rows"][0]["author_name"] = {"raw_document": "private"}

    with pytest.raises(ValidationError, match="prepared"):
        IngestionBatch.objects.create(
            organization=organization,
            source_type=IngestionBatch.SourceType.URL,
            input_reference=reference,
            idempotency_key="prepared-smuggle",
        )


@pytest.mark.django_db
def test_raw_csv_columns_and_paste_document_are_not_persisted(organization):
    csv_document = (
        "source_url,original_text,cookie,authorization,raw_headers\n"
        "https://e.test/csv,Public,session=private,Bearer private,X-Secret"
    )
    paste_document = "https://e.test/paste\tCustomer mentioned cookie dimensions."
    csv_batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.CSV,
        input_reference=prepare_import_reference(csv_document, source_type="CSV"),
        idempotency_key="prepared-csv-no-raw",
    )
    paste_batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=prepare_import_reference(paste_document, source_type="PASTE"),
        idempotency_key="prepared-paste-no-raw",
    )
    csv_batch.refresh_from_db()
    paste_batch.refresh_from_db()

    csv_persisted = json.dumps(csv_batch.input_reference, sort_keys=True)
    paste_persisted = json.dumps(paste_batch.input_reference, sort_keys=True)
    assert csv_document not in csv_persisted
    assert "session=private" not in csv_persisted
    assert "Bearer private" not in csv_persisted
    assert "X-Secret" not in csv_persisted
    assert paste_document not in paste_persisted
    assert paste_batch.input_reference["rows"][0]["original_text"] == (
        "Customer mentioned cookie dimensions."
    )


@pytest.mark.django_db
def test_prepared_source_type_binding_is_enforced_on_every_batch_write_path(organization):
    paste_reference = prepare_import_reference(
        {"text": "https://e.test/paste\tPaste"}, source_type="PASTE"
    )
    mismatch = {
        "organization": organization,
        "source_type": IngestionBatch.SourceType.URL,
        "input_reference": paste_reference,
    }
    with pytest.raises(ValidationError, match="source type"):
        IngestionBatch.objects.create(idempotency_key="type-create", **mismatch)
    with pytest.raises(ValidationError, match="source type"):
        IngestionBatch.objects.bulk_create(
            [IngestionBatch(idempotency_key="type-bulk-create", **mismatch)]
        )

    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=paste_reference,
        idempotency_key="type-correct",
    )
    batch.source_type = IngestionBatch.SourceType.URL
    with pytest.raises(ValidationError, match="source type"):
        batch.save()
    batch.refresh_from_db()
    with pytest.raises(ValidationError, match="source type"):
        IngestionBatch.objects.filter(pk=batch.pk).update(
            source_type=IngestionBatch.SourceType.CSV
        )
    batch.refresh_from_db()
    batch.source_type = IngestionBatch.SourceType.JSON
    with pytest.raises(ValidationError, match="source type"):
        IngestionBatch.objects.bulk_update([batch], ["source_type"])
    batch.refresh_from_db()
    assert batch.source_type == IngestionBatch.SourceType.PASTE
