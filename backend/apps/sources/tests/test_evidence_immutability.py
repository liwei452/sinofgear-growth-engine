import pytest
from django.core.exceptions import ValidationError

from apps.sources.models import IngestionRow, SourceEvidence, evidence_service_writes, ingestion_row_service_writes
from apps.sources.services import EvidenceService, evidence_fingerprint


@pytest.mark.django_db
def test_evidence_service_deduplicates_and_direct_update_is_rejected(signal, user):
    kwargs = dict(
        organization=signal.organization,
        signal=signal,
        original_text="We need 200 replacement helical gears.",
        source_url="https://example.com/posts/42",
        platform="MANUAL",
        collection_method="PASTE",
        public_published_at=None,
        created_by=user,
    )
    first = EvidenceService.create(**kwargs)
    second = EvidenceService.create(**kwargs)
    assert second.id == first.id
    assert first.retention_class == SourceEvidence.RetentionClass.TRANSIENT_30D
    assert first.evidence_type == SourceEvidence.EvidenceType.PUBLIC_TEXT
    with pytest.raises(ValidationError, match="service"):
        SourceEvidence.objects.filter(pk=first.pk).update(original_text="changed")

    with pytest.raises(ValidationError):
        EvidenceService.create(**{**kwargs, "collection_method": "UNSUPPORTED"})
    with pytest.raises(ValidationError):
        EvidenceService.create(**{**kwargs, "evidence_type": "UNSUPPORTED"})


@pytest.mark.django_db
def test_committed_evidence_rejects_all_ordinary_write_paths(signal, user):
    evidence = EvidenceService.create(
        organization=signal.organization,
        signal=signal,
        original_text="Public request",
        source_url="https://example.com/request#comments",
        platform="manual",
        collection_method="URL",
        public_published_at=None,
        created_by=user,
    )
    evidence.original_text = "changed"
    with pytest.raises(ValidationError, match="service"):
        evidence.save()
    with pytest.raises(ValidationError, match="service"):
        evidence.delete()
    with pytest.raises(ValidationError, match="service"):
        SourceEvidence.objects.filter(pk=evidence.pk).delete()
    with pytest.raises(ValidationError, match="service"):
        SourceEvidence.objects.bulk_update([evidence], ["original_text"])
    with pytest.raises(ValidationError, match="service"):
        SourceEvidence.objects.bulk_create([evidence])


@pytest.mark.django_db
def test_controlled_context_can_redact_without_exposing_ordinary_writes(signal, user):
    evidence = EvidenceService.create(
        organization=signal.organization,
        signal=signal,
        original_text="Temporary public text",
        source_url="https://example.com/temp",
        platform="MANUAL",
        collection_method="PASTE",
        public_published_at=None,
        created_by=user,
    )
    with evidence_service_writes():
        SourceEvidence.objects.filter(pk=evidence.pk).update(
            original_text="",
            source_url="HTTPS://Example.COM:443/redacted#fragment",
            availability=SourceEvidence.Availability.REDACTED_BY_RETENTION,
        )
    evidence.refresh_from_db()
    assert evidence.original_text == ""
    assert evidence.source_url == "https://example.com/redacted"
    assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION


def test_evidence_fingerprint_normalizes_equivalent_facts():
    first = evidence_fingerprint(
        original_text="  We need  200 gears.\n",
        source_url="HTTPS://Example.COM:443/posts/42#fragment",
        platform=" manual ",
    )
    second = evidence_fingerprint(
        original_text="We need 200 gears.",
        source_url="https://example.com/posts/42",
        platform="MANUAL",
    )
    assert first == second == "88f239f001b04fef586edd0df4f1643085a783d95a27745ba97e469ee88fe861"


@pytest.mark.django_db
def test_ingestion_row_is_service_write_only(organization, job):
    from apps.sources.models import IngestionBatch

    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        idempotency_key="batch-row-guard",
        job=job,
    )
    row = IngestionRow(
        organization=organization,
        batch=batch,
        row_number=1,
        normalized_input={"text": "public request"},
        outcome=IngestionRow.Outcome.ACCEPTED,
    )
    with pytest.raises(ValidationError, match="service"):
        row.save()
    with ingestion_row_service_writes():
        row.save()
    with pytest.raises(ValidationError, match="service"):
        IngestionRow.objects.filter(pk=row.pk).update(outcome=IngestionRow.Outcome.FAILED)
    with pytest.raises(ValidationError, match="service"):
        row.delete()
