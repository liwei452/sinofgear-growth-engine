import pytest
from django.core.exceptions import ValidationError

from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.sources.importers import prepare_import_reference
from apps.sources.models import IngestionBatch, IngestionRow, SourceContent, SourceSignal, ingestion_row_service_writes
from apps.sources.services import EvidenceService


@pytest.mark.django_db
def test_source_content_cannot_reference_another_organization(target, other_organization):
    content = SourceContent(
        organization=other_organization,
        monitoring_target=target,
        platform="MANUAL",
        canonical_url="https://example.com/post",
        content_hash="a" * 64,
    )
    with pytest.raises(ValidationError):
        content.full_clean()


@pytest.mark.django_db
def test_signal_requires_same_organization_and_a_source(target, content, other_organization):
    missing = SourceSignal(
        organization=target.organization,
        signal_type=SourceSignal.SignalType.MENTION,
        platform="MANUAL",
    )
    with pytest.raises(ValidationError):
        missing.full_clean()

    mismatched = SourceSignal(
        organization=other_organization,
        monitoring_target=target,
        source_content=content,
        signal_type=SourceSignal.SignalType.MENTION,
        platform="MANUAL",
    )
    with pytest.raises(ValidationError):
        mismatched.full_clean()


@pytest.mark.django_db
def test_batch_and_row_reject_cross_organization_foreign_keys(
    organization, other_organization, target, signal, user
):
    other_job = JobService.create(
        organization=other_organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"source": "other"},
        idempotency_key="other-source-job",
        created_by=user,
    )
    batch = IngestionBatch(
        organization=organization,
        source_type=IngestionBatch.SourceType.URL,
        idempotency_key="bad-batch",
        monitoring_target=target,
        job=other_job,
        input_reference=prepare_import_reference(
            {"source_url": "https://e.test/bad", "original_text": "Public"},
            source_type="URL",
        ),
    )
    with pytest.raises(ValidationError):
        batch.full_clean()

    valid_batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.URL,
        idempotency_key="valid-batch",
        monitoring_target=target,
        input_reference=prepare_import_reference(
            {"source_url": "https://e.test/valid", "original_text": "Public"},
            source_type="URL",
        ),
    )
    row = IngestionRow(
        organization=other_organization,
        batch=valid_batch,
        row_number=1,
        normalized_input={},
        outcome=IngestionRow.Outcome.ACCEPTED,
        source_signal=signal,
    )
    with pytest.raises(ValidationError):
        row.full_clean()
    with pytest.raises(ValidationError), ingestion_row_service_writes():
        row.save()


@pytest.mark.django_db
def test_evidence_service_rejects_cross_organization_assets(signal, user, other_asset):
    with pytest.raises(ValidationError):
        EvidenceService.create(
            organization=signal.organization,
            signal=signal,
            original_text="Public screenshot text",
            source_url="https://example.com/screenshot",
            platform="MANUAL",
            collection_method="SCREENSHOT",
            public_published_at=None,
            created_by=user,
            screenshot_asset=other_asset,
        )
