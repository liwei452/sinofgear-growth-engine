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
from apps.sources.services import EvidenceService


def _write_context(instance):
    if isinstance(instance, SourceEvidence):
        return evidence_service_writes()
    if isinstance(instance, IngestionRow):
        return ingestion_row_service_writes()
    return nullcontext()


@pytest.mark.django_db
def test_persisted_source_organization_is_immutable_through_every_orm_path(
    organization, other_organization, target, content, signal, user
):
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
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
        source_type=IngestionBatch.SourceType.JSON,
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
