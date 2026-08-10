import json
import uuid
from copy import deepcopy
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.ai.models import AIRun, PromptVersion, ai_audit_writes
from apps.ai.services import PromptVersionService
from apps.assets.models import MaterialAsset
from apps.audit.models import AuditLog
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.leads.models import LeadCandidate, LeadReview, lead_history_writes
from apps.leads.services import LeadService
from apps.sources.models import (
    IngestionBatch,
    IngestionBatchQuerySet,
    IngestionRow,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
    evidence_service_writes,
    ingestion_row_service_writes,
)
from apps.sources.importers import prepare_import_reference
from apps.sources.services import (
    EvidenceService,
    IngestionService,
    RetentionService,
    SourceIdempotencyConflictError,
    SourceIngestionRequestService,
    canonical_source_evidence_snapshot,
    source_import_job_snapshot,
)
from apps.sources.tasks import execute_source_import


@pytest.fixture
def source_manager(organization):
    actor = get_user_model().objects.create_user(username="retention-manager")
    Membership.objects.create(
        user=actor,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    return actor


def _asset(*, organization, user, marker):
    asset_id = uuid.uuid4()
    return MaterialAsset.objects.create(
        id=asset_id,
        organization=organization,
        asset_type=MaterialAsset.AssetType.IMAGE,
        storage_key=f"organizations/{organization.id}/assets/{asset_id}/original",
        original_filename=f"{marker}.png",
        mime_type="image/png",
        size_bytes=1,
        checksum=(marker.encode().hex() + "0" * 64)[:64],
        created_by=user,
    )


def _evidence(
    *,
    organization,
    user,
    marker,
    captured_at,
    text=None,
    translated_text="",
    retention_class=SourceEvidence.RetentionClass.TRANSIENT_30D,
    screenshot_asset=None,
    import_asset=None,
):
    source_text = text or f"Private public trace {marker}"
    target = MonitoringTarget.objects.create(
        organization=organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.PASTE,
        platform="MANUAL",
        normalized_url=f"https://example.com/posts/{marker}",
        label=f"Retention {marker}",
        created_by=user,
    )
    content = SourceContent.objects.create(
        organization=organization,
        monitoring_target=target,
        platform="MANUAL",
        external_id=f"post-{marker}",
        canonical_url=f"https://example.com/posts/{marker}",
        author_public_name=f"Public Person {marker}",
        original_text=source_text,
        captured_at=captured_at,
        content_hash=(marker.encode().hex() + "0" * 64)[:64],
        created_by=user,
    )
    signal = SourceSignal.objects.create(
        organization=organization,
        monitoring_target=target,
        source_content=content,
        signal_type=SourceSignal.SignalType.COMMENT,
        platform="MANUAL",
        external_id=f"comment-{marker}",
        captured_at=captured_at,
        created_by=user,
    )
    evidence = EvidenceService.create(
        organization=organization,
        signal=signal,
        original_text=source_text,
        source_url=content.canonical_url,
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.PASTE,
        public_published_at=captured_at,
        created_by=user,
        screenshot_asset=screenshot_asset,
        import_asset=import_asset,
        language="en",
    )
    with evidence_service_writes():
        evidence.captured_at = captured_at
        evidence.translated_text = translated_text
        evidence.translated_language = "zh" if translated_text else ""
        evidence.retention_class = retention_class
        evidence.save(
            update_fields=[
                "captured_at",
                "translated_text",
                "translated_language",
                "retention_class",
                "updated_at",
            ]
        )
    return evidence


def _attach_ingestion_copy(*, evidence, user, author_name, screenshot_asset):
    organization = evidence.organization
    reference = prepare_import_reference(
        {
            "source_url": evidence.source_url,
            "original_text": evidence.original_text,
            "author_name": author_name,
            "screenshot_asset_id": str(screenshot_asset.id),
        },
        source_type=IngestionBatch.SourceType.SCREENSHOT,
    )
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        input_reference=reference,
        idempotency_key=f"retention-copy-{evidence.id}",
        created_by=user,
    )
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot=source_import_job_snapshot(batch),
        idempotency_key=batch.idempotency_key,
        created_by=user,
    )
    batch.job = job
    batch.save(update_fields=["job", "updated_at"])
    normalized = dict(reference["rows"][0])
    normalized.pop("row_number")
    with ingestion_row_service_writes():
        row = IngestionRow.objects.create(
            organization=organization,
            batch=batch,
            row_number=1,
            normalized_input=normalized,
            outcome=IngestionRow.Outcome.ACCEPTED,
            source_content=evidence.source_signal.source_content,
            source_signal=evidence.source_signal,
            source_evidence=evidence,
        )
    IngestionService._finish_batch(batch)
    claimed = JobService.claim(
        worker_id="completed-source-import",
        job_id=job.id,
        job_type=Job.Type.SOURCE_IMPORT,
    )
    JobService.succeed(
        job.id,
        claim_token=claimed.claim_token,
        result_reference={"ingestion_batch_id": str(batch.id)},
    )
    return batch, row


def _request_and_run_import(
    *,
    organization,
    user,
    key,
    payload,
    source_type,
    monkeypatch,
    import_asset_id=None,
):
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *_args: None)
    reference = prepare_import_reference(payload, source_type=source_type)
    batch, job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=source_type,
        idempotency_key=key,
        prepared_reference=reference,
        import_asset_id=import_asset_id,
    )
    result = execute_source_import(str(job.id), str(batch.id))
    assert result["status"] == IngestionBatch.Status.SUCCEEDED
    batch.refresh_from_db()
    return batch


def _make_imported_evidence_old(*, batch, cutoff):
    evidence_rows = list(
        SourceEvidence.objects.filter(ingestion_rows__batch=batch).order_by("pk")
    )
    with evidence_service_writes():
        for evidence in evidence_rows:
            evidence.captured_at = cutoff - timedelta(days=1)
            evidence.save(update_fields=["captured_at", "updated_at"])
    return evidence_rows


@pytest.mark.django_db
def test_cleanup_redacts_old_transient_evidence_and_preserves_fingerprint_history(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    screenshot = _asset(organization=organization, user=user, marker="ret-screen")
    imported = _asset(organization=organization, user=user, marker="ret-import")
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="old",
        captured_at=cutoff - timedelta(seconds=1),
        text="We need 200 replacement gears from Jane Buyer",
        translated_text="我们需要二百个替换齿轮",
        screenshot_asset=screenshot,
        import_asset=imported,
    )
    original_hash = evidence.content_hash
    candidate = LeadService.create_candidate(
        organization=organization,
        creator=user,
        company_name="Example Packaging",
        company_domain="example.com",
        country_hint="DE",
        evidence_ids=[evidence.id],
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    evidence.source_signal.source_content.refresh_from_db()
    assert evidence.original_text == ""
    assert evidence.translated_text == ""
    assert evidence.translated_language == ""
    assert evidence.screenshot_asset_id is None
    assert evidence.import_asset_id is None
    assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    assert evidence.retention_class == SourceEvidence.RetentionClass.TRANSIENT_30D
    assert evidence.content_hash == original_hash
    assert evidence.source_signal.source_content.author_public_name == ""
    assert evidence.source_signal.source_content.original_text == ""
    assert candidate.evidence_links.filter(evidence=evidence).exists()
    assert SourceEvidence.objects.filter(pk=evidence.pk).exists()
    assert result.redacted == 1
    assert result.deleted_text == 3
    assert result.anonymized_actors == 1
    assert result.protected == 0
    assert result.failures == 0
    assert result.no_op == 0


@pytest.mark.django_db
def test_cleanup_tombstones_every_linked_ingestion_raw_copy(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    secret_text = "SECRET-RAW-TEXT need custom gears"
    secret_author = "SECRET-AUTHOR-HANDLE"
    screenshot = _asset(
        organization=organization,
        user=user,
        marker="raw-copy-screen",
    )
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="raw-copy",
        captured_at=cutoff - timedelta(days=1),
        text=secret_text,
        screenshot_asset=screenshot,
    )
    content = evidence.source_signal.source_content
    content.author_public_name = secret_author
    content.save(update_fields=["author_public_name", "updated_at"])
    batch, row = _attach_ingestion_copy(
        evidence=evidence,
        user=user,
        author_name=secret_author,
        screenshot_asset=screenshot,
    )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    evidence.refresh_from_db()
    content.refresh_from_db()
    batch.refresh_from_db()
    row.refresh_from_db()
    batch.full_clean()
    materialized = json.dumps(
        {
            "evidence": {
                "original_text": evidence.original_text,
                "translated_text": evidence.translated_text,
                "screenshot_asset_id": str(evidence.screenshot_asset_id),
                "import_asset_id": str(evidence.import_asset_id),
            },
            "content": {
                "original_text": content.original_text,
                "author_public_name": content.author_public_name,
            },
            "batch": batch.input_reference,
            "row": row.normalized_input,
        },
        sort_keys=True,
    )
    assert secret_text not in materialized
    assert secret_author not in materialized
    assert str(screenshot.id) not in materialized
    assert batch.input_reference["retention"]["reason"] == "TRANSIENT_30D_EXPIRED"
    assert row.normalized_input["retention"]["reason"] == "TRANSIENT_30D_EXPIRED"
    assert result.redacted == 1
    assert result.deleted_text == 4
    assert result.anonymized_actors == 3


@pytest.mark.django_db
def test_cleanup_redacts_every_independent_row_in_completed_batch_without_shared_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-two-independent-rows",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/independent-one",
                    "original_text": "FIRST-INDEPENDENT-SECRET",
                    "author_name": "FIRST-INDEPENDENT-AUTHOR",
                },
                {
                    "source_url": "https://example.com/posts/independent-two",
                    "original_text": "SECOND-INDEPENDENT-SECRET",
                    "author_name": "SECOND-INDEPENDENT-AUTHOR",
                },
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    evidence_rows = _make_imported_evidence_old(batch=batch, cutoff=cutoff)

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    ingestion_rows = list(batch.rows.order_by("row_number"))
    materialized = json.dumps(
        {
            "batch": batch.input_reference,
            "rows": [row.normalized_input for row in ingestion_rows],
        },
        sort_keys=True,
    )
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
        assert evidence.original_text == ""
    assert "FIRST-INDEPENDENT-SECRET" not in materialized
    assert "SECOND-INDEPENDENT-SECRET" not in materialized
    assert batch.input_reference["retention"]["redacted_row_numbers"] == [1, 2]
    assert [
        row.normalized_input["retention"]["source_evidence_id"]
        for row in ingestion_rows
    ] == [str(row.source_evidence_id) for row in ingestion_rows]
    assert result.redacted == 2
    assert result.protected == 0
    assert result.failures == 0


@pytest.mark.django_db
def test_cleanup_redacts_every_csv_row_in_completed_batch_without_shared_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-two-independent-csv-rows",
        payload=(
            "source_url,original_text,author_name\n"
            "https://example.com/posts/csv-one,CSV-FIRST-SECRET,CSV-FIRST-AUTHOR\n"
            "https://example.com/posts/csv-two,CSV-SECOND-SECRET,CSV-SECOND-AUTHOR"
        ),
        source_type=IngestionBatch.SourceType.CSV,
        monkeypatch=monkeypatch,
    )
    evidence_rows = _make_imported_evidence_old(batch=batch, cutoff=cutoff)

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    materialized = json.dumps(batch.input_reference, sort_keys=True)
    assert "CSV-FIRST-SECRET" not in materialized
    assert "CSV-SECOND-SECRET" not in materialized
    assert batch.input_reference["retention"]["redacted_row_numbers"] == [2, 3]
    assert result.redacted == 2
    assert result.protected == 0
    assert result.failures == 0


@pytest.mark.django_db
def test_cleanup_selectively_redacts_transient_row_in_mixed_batch_without_shared_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    transient_secret = "MIXED-TRANSIENT-SECRET"
    protected_secret = "MIXED-PROTECTED-SECRET"
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-mixed-independent-rows",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/mixed-transient",
                    "original_text": transient_secret,
                },
                {
                    "source_url": "https://example.com/posts/mixed-protected",
                    "original_text": protected_secret,
                },
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    evidence_rows = _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    rows_by_number = {row.row_number: row for row in batch.rows.all()}
    protected = rows_by_number[2].source_evidence
    with evidence_service_writes():
        protected.retention_class = SourceEvidence.RetentionClass.CONFIRMED
        protected.save(update_fields=["retention_class", "updated_at"])

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    for evidence in evidence_rows:
        evidence.refresh_from_db()
    transient = rows_by_number[1].source_evidence
    transient.refresh_from_db()
    protected.refresh_from_db()
    assert transient.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    assert protected.availability == SourceEvidence.Availability.AVAILABLE
    assert transient_secret not in json.dumps(batch.input_reference, sort_keys=True)
    assert protected_secret in json.dumps(batch.input_reference, sort_keys=True)
    assert batch.input_reference["retention"]["redacted_row_numbers"] == [1]
    assert result.redacted == 1
    assert result.protected == 1
    assert result.failures == 0


@pytest.mark.django_db
def test_cleanup_atomically_redacts_all_rows_that_share_batch_import_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="shared-import-document",
    )
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-shared-import-asset",
        payload={
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": "https://example.com/posts/shared-import-one",
                    "original_text": "SHARED-IMPORT-FIRST",
                },
                {
                    "source_url": "https://example.com/posts/shared-import-two",
                    "original_text": "SHARED-IMPORT-SECOND",
                },
            ],
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    evidence_rows = _make_imported_evidence_old(batch=batch, cutoff=cutoff)

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    second_result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    batch.full_clean()
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
        assert evidence.import_asset_id is None
    assert "import_asset_id" not in batch.input_reference
    assert batch.input_reference["retention"]["redacted_row_numbers"] == [1, 2]
    assert result.redacted == 2
    assert result.protected == 0
    assert result.failures == 0
    assert second_result.redacted == 0
    assert second_result.deleted_text == 0
    assert second_result.anonymized_actors == 0
    assert second_result.no_op == 2


@pytest.mark.django_db
def test_cleanup_protects_entire_shared_import_asset_batch_when_one_row_is_confirmed(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="mixed-shared-import-document",
    )
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-mixed-shared-import-asset",
        payload={
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": "https://example.com/posts/shared-mixed-transient",
                    "original_text": "SHARED-MIXED-TRANSIENT",
                },
                {
                    "source_url": "https://example.com/posts/shared-mixed-confirmed",
                    "original_text": "SHARED-MIXED-CONFIRMED",
                },
            ],
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    rows_by_number = {row.row_number: row for row in batch.rows.all()}
    transient = rows_by_number[1].source_evidence
    confirmed = rows_by_number[2].source_evidence
    with evidence_service_writes():
        confirmed.retention_class = SourceEvidence.RetentionClass.CONFIRMED
        confirmed.save(update_fields=["retention_class", "updated_at"])
    original_reference = batch.input_reference

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    transient.refresh_from_db()
    confirmed.refresh_from_db()
    assert batch.input_reference == original_reference
    assert batch.input_reference["import_asset_id"] == str(import_asset.id)
    assert transient.availability == SourceEvidence.Availability.AVAILABLE
    assert confirmed.availability == SourceEvidence.Availability.AVAILABLE
    assert transient.import_asset_id == import_asset.id
    assert confirmed.import_asset_id == import_asset.id
    assert result.redacted == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.protected_reasons == {
        "NON_TRANSIENT_RETENTION_CLASS": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_cleanup_protects_every_batch_that_reused_a_shared_import_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="cross-batch-shared-document",
    )
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-cross-batch-shared-{index}",
            payload={
                "import_asset_id": str(import_asset.id),
                "rows": [
                    {
                        "source_url": f"https://example.com/posts/cross-batch-{index}",
                        "original_text": f"CROSS-BATCH-SECRET-{index}",
                    }
                ],
            },
            source_type=IngestionBatch.SourceType.JSON,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]
    confirmed = evidence_rows[1]
    with evidence_service_writes():
        confirmed.retention_class = SourceEvidence.RetentionClass.CONFIRMED
        confirmed.save(update_fields=["retention_class", "updated_at"])
    original_references = [deepcopy(batch.input_reference) for batch in batches]

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch, original_reference in zip(batches, original_references, strict=True):
        batch.refresh_from_db()
        assert batch.input_reference == original_reference
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.import_asset_id == import_asset.id
        assert evidence.original_text
    assert result.redacted == 0
    assert result.deleted_text == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.protected_reasons == {
        "NON_TRANSIENT_RETENTION_CLASS": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_cleanup_atomically_redacts_batches_sharing_screenshot_identity(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    screenshot = _asset(
        organization=organization,
        user=user,
        marker="cross-batch-shared-screenshot",
    )
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-cross-batch-screenshot-{index}",
            payload={
                "source_url": f"https://example.com/posts/shared-screen-{index}",
                "original_text": f"SHARED-SCREENSHOT-SECRET-{index}",
                "screenshot_asset_id": str(screenshot.id),
            },
            source_type=IngestionBatch.SourceType.SCREENSHOT,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]

    first = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    second = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    assert first.redacted == 2
    assert second.redacted == 0
    assert second.no_op == 2
    for batch, evidence in zip(batches, evidence_rows, strict=True):
        batch.refresh_from_db()
        row = batch.rows.get()
        evidence.refresh_from_db()
        assert evidence.screenshot_asset_id is None
        assert row.request_screenshot_asset_id == screenshot.id
        assert row.normalized_input["screenshot_asset_id"] is None
        assert batch.input_reference["rows"][0]["screenshot_asset_id"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("blocker", ["confirmed", "young"])
def test_shared_screenshot_group_waits_until_every_member_is_eligible(
    organization, user, source_manager, monkeypatch, blocker
):
    cutoff = timezone.now() - timedelta(days=30)
    screenshot = _asset(
        organization=organization,
        user=user,
        marker=f"shared-screenshot-{blocker}",
    )
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-shared-screen-{blocker}-{index}",
            payload={
                "source_url": f"https://example.com/posts/screen-{blocker}-{index}",
                "original_text": f"SCREEN-{blocker.upper()}-{index}",
                "screenshot_asset_id": str(screenshot.id),
            },
            source_type=IngestionBatch.SourceType.SCREENSHOT,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence_rows = [batch.rows.get().source_evidence for batch in batches]
    for evidence in evidence_rows:
        with evidence_service_writes():
            evidence.captured_at = cutoff - timedelta(days=1)
            evidence.save(update_fields=["captured_at", "updated_at"])
    blocked = evidence_rows[1]
    with evidence_service_writes():
        if blocker == "confirmed":
            blocked.retention_class = SourceEvidence.RetentionClass.CONFIRMED
            blocked.save(update_fields=["retention_class", "updated_at"])
        else:
            blocked.captured_at = cutoff + timedelta(days=1)
            blocked.save(update_fields=["captured_at", "updated_at"])

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    assert result.redacted == 0
    assert result.protected == 2
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.screenshot_asset_id == screenshot.id


@pytest.mark.django_db
def test_screenshot_and_json_import_using_same_asset_share_one_component(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    shared_asset = _asset(
        organization=organization,
        user=user,
        marker="mixed-screenshot-json",
    )
    screenshot_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-mixed-screenshot",
        payload={
            "source_url": "https://example.com/posts/mixed-screenshot",
            "original_text": "MIXED-SCREENSHOT-SECRET",
            "screenshot_asset_id": str(shared_asset.id),
        },
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        monkeypatch=monkeypatch,
    )
    json_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-mixed-json",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/mixed-json",
                    "original_text": "MIXED-JSON-SECRET",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=shared_asset.id,
        monkeypatch=monkeypatch,
    )
    evidences = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in (screenshot_batch, json_batch)
    ]

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    assert result.redacted == 2
    assert all(
        SourceEvidence.objects.get(pk=evidence.pk).availability
        == SourceEvidence.Availability.REDACTED_BY_RETENTION
        for evidence in evidences
    )


@pytest.mark.django_db
def test_cleanup_atomically_redacts_cross_batch_cross_type_shared_asset_component(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="cross-type-shared-document",
    )
    json_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-cross-type-json",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/cross-type-json",
                    "original_text": "CROSS-TYPE-JSON-SECRET",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    csv_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-cross-type-csv",
        payload=(
            "source_url,original_text\n"
            "https://example.com/posts/cross-type-csv,CROSS-TYPE-CSV-SECRET"
        ),
        source_type=IngestionBatch.SourceType.CSV,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    batches = [json_batch, csv_batch]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]
    original_identities = [
        (batch.prepared_reference_sha256, batch.request_import_asset_id)
        for batch in batches
    ]

    first_result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    second_result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch, original_identity in zip(batches, original_identities, strict=True):
        batch.refresh_from_db()
        batch.full_clean()
        assert "import_asset_id" not in batch.input_reference
        assert batch.input_reference["retention"]["reason"] == (
            "TRANSIENT_30D_EXPIRED"
        )
        assert (
            batch.prepared_reference_sha256,
            batch.request_import_asset_id,
        ) == original_identity
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
        assert evidence.import_asset_id is None
        assert evidence.original_text == ""
    assert first_result.redacted == 2
    assert first_result.protected == 0
    assert first_result.failures == 0
    assert second_result.redacted == 0
    assert second_result.deleted_text == 0
    assert second_result.anonymized_actors == 0
    assert second_result.no_op == 2


@pytest.mark.django_db
def test_cleanup_protects_shared_asset_group_when_another_batch_is_not_expired(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="cross-batch-younger-document",
    )
    old_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-cross-batch-old",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/cross-batch-old",
                    "original_text": "CROSS-BATCH-OLD-SECRET",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    younger_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-cross-batch-younger",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/cross-batch-younger",
                    "original_text": "CROSS-BATCH-YOUNGER-SECRET",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    old_evidence = _make_imported_evidence_old(
        batch=old_batch, cutoff=cutoff
    )[0]
    younger_evidence = SourceEvidence.objects.get(
        ingestion_rows__batch=younger_batch
    )
    original_references = [
        deepcopy(old_batch.input_reference),
        deepcopy(younger_batch.input_reference),
    ]

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch, reference in zip(
        [old_batch, younger_batch], original_references, strict=True
    ):
        batch.refresh_from_db()
        assert batch.input_reference == reference
    old_evidence.refresh_from_db()
    younger_evidence.refresh_from_db()
    assert old_evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert younger_evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.protected_reasons == {
        "RETENTION_NOT_EXPIRED": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_cleanup_fails_closed_for_incomplete_shared_import_asset_batch(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="incomplete-shared-import-document",
    )
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="incomplete-shared-import",
        captured_at=cutoff - timedelta(days=1),
        text="INCOMPLETE-SHARED-FIRST",
        import_asset=import_asset,
    )
    reference = prepare_import_reference(
        {
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": evidence.source_url,
                    "original_text": evidence.original_text,
                },
                {
                    "source_url": "https://example.com/posts/incomplete-missing-row",
                    "original_text": "INCOMPLETE-SHARED-MISSING",
                },
            ],
        },
        source_type=IngestionBatch.SourceType.JSON,
    )
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.JSON,
        input_reference=reference,
        idempotency_key="retention-incomplete-shared-import",
        created_by=user,
    )
    normalized = dict(reference["rows"][0])
    normalized.pop("row_number")
    with ingestion_row_service_writes():
        IngestionRow.objects.create(
            organization=organization,
            batch=batch,
            row_number=1,
            normalized_input=normalized,
            outcome=IngestionRow.Outcome.ACCEPTED,
            source_content=evidence.source_signal.source_content,
            source_signal=evidence.source_signal,
            source_evidence=evidence,
        )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    evidence.refresh_from_db()
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert evidence.original_text == "INCOMPLETE-SHARED-FIRST"
    assert batch.input_reference == reference
    assert result.redacted == 0
    assert result.protected == 1
    assert result.failures == 0
    assert result.deleted_text == 0
    assert result.protected_reasons == {
        "SHARED_IMPORT_ASSET_INCONSISTENT": 1,
    }


@pytest.mark.django_db
def test_cleanup_shared_import_asset_group_rolls_back_when_second_evidence_fails(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="rollback-shared-import-document",
    )
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-rollback-shared-import-asset",
        payload={
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": "https://example.com/posts/rollback-shared-one",
                    "original_text": "ROLLBACK-SHARED-FIRST",
                },
                {
                    "source_url": "https://example.com/posts/rollback-shared-two",
                    "original_text": "ROLLBACK-SHARED-SECOND",
                },
            ],
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    evidence_rows = _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    original_reference = batch.input_reference
    original_redact = RetentionService._redact_locked
    calls = []

    def fail_second(evidence, **kwargs):
        calls.append(evidence.id)
        if len(calls) == 2:
            raise ValidationError("simulated second evidence failure")
        return original_redact(evidence, **kwargs)

    monkeypatch.setattr(RetentionService, "_redact_locked", fail_second)

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        evidence.source_signal.source_content.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.original_text
        assert evidence.import_asset_id == import_asset.id
        assert evidence.source_signal.source_content.original_text
    assert batch.input_reference == original_reference
    assert result.redacted == 0
    assert result.deleted_text == 0
    assert result.anonymized_actors == 0
    assert result.failures == 2


@pytest.mark.django_db
def test_cleanup_cross_batch_asset_group_rolls_back_when_second_batch_write_fails(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="rollback-cross-batch-document",
    )
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-rollback-cross-batch-{index}",
            payload={
                "rows": [
                    {
                        "source_url": f"https://example.com/posts/rollback-cross-{index}",
                        "original_text": f"ROLLBACK-CROSS-BATCH-{index}",
                    }
                ]
            },
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=import_asset.id,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]
    original_references = [deepcopy(batch.input_reference) for batch in batches]
    original_writer = IngestionBatchQuerySet._service_tombstone_input_reference
    calls = []

    def fail_second_batch(queryset, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise ValidationError("simulated second batch tombstone failure")
        return original_writer(queryset, **kwargs)

    monkeypatch.setattr(
        IngestionBatchQuerySet,
        "_service_tombstone_input_reference",
        fail_second_batch,
    )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch, reference in zip(batches, original_references, strict=True):
        batch.refresh_from_db()
        assert batch.input_reference == reference
    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.import_asset_id == import_asset.id
        assert evidence.original_text
    assert calls == [True, True]
    assert result.redacted == 0
    assert result.deleted_text == 0
    assert result.anonymized_actors == 0
    assert result.protected == 0
    assert result.failures == 2


@pytest.mark.django_db
def test_cleanup_cross_batch_asset_group_fails_closed_for_missing_sibling_row(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="inconsistent-cross-batch-document",
    )
    valid_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-inconsistent-cross-valid",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/inconsistent-cross-valid",
                    "original_text": "INCONSISTENT-CROSS-VALID",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    valid_evidence = _make_imported_evidence_old(
        batch=valid_batch, cutoff=cutoff
    )[0]
    sibling_evidence = _evidence(
        organization=organization,
        user=user,
        marker="inconsistent-cross-sibling",
        captured_at=cutoff - timedelta(days=1),
        text="INCONSISTENT-CROSS-SIBLING",
        import_asset=import_asset,
    )
    reference = prepare_import_reference(
        {
            "import_asset_id": str(import_asset.id),
            "rows": [
                {
                    "source_url": sibling_evidence.source_url,
                    "original_text": sibling_evidence.original_text,
                },
                {
                    "source_url": "https://example.com/posts/inconsistent-cross-missing",
                    "original_text": "INCONSISTENT-CROSS-MISSING",
                },
            ],
        },
        source_type=IngestionBatch.SourceType.JSON,
    )
    incomplete_batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.JSON,
        input_reference=reference,
        idempotency_key="retention-inconsistent-cross-incomplete",
        created_by=user,
    )
    normalized = dict(reference["rows"][0])
    normalized.pop("row_number")
    with ingestion_row_service_writes():
        IngestionRow.objects.create(
            organization=organization,
            batch=incomplete_batch,
            row_number=1,
            normalized_input=normalized,
            outcome=IngestionRow.Outcome.ACCEPTED,
            source_content=sibling_evidence.source_signal.source_content,
            source_signal=sibling_evidence.source_signal,
            source_evidence=sibling_evidence,
        )
    IngestionService._finish_batch(incomplete_batch)
    original_references = [
        deepcopy(valid_batch.input_reference),
        deepcopy(incomplete_batch.input_reference),
    ]

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch, original_reference in zip(
        [valid_batch, incomplete_batch], original_references, strict=True
    ):
        batch.refresh_from_db()
        assert batch.input_reference == original_reference
    for evidence in [valid_evidence, sibling_evidence]:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.original_text
    assert result.redacted == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.deleted_text == 0
    assert result.protected_reasons == {
        "SHARED_IMPORT_ASSET_INCONSISTENT": 2,
    }


@pytest.mark.django_db
def test_new_key_cannot_reuse_cleaned_shared_import_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="late-cross-batch-document",
    )
    secret = "LATE-CROSS-BATCH-DUPLICATE-SECRET"
    payloads = [
        {
            "rows": [
                {
                    "source_url": "https://example.com/posts/late-cross-duplicate",
                    "original_text": secret,
                }
            ]
        },
        {
            "rows": [
                {
                    "source_url": "https://example.com/posts/late-cross-neighbor",
                    "original_text": "LATE-CROSS-BATCH-NEIGHBOR",
                }
            ]
        },
    ]
    original_batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-late-cross-original-{index}",
            payload=payload,
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=import_asset.id,
            monkeypatch=monkeypatch,
        )
        for index, payload in enumerate(payloads, start=1)
    ]
    for batch in original_batches:
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    first_cleanup = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    assert first_cleanup.redacted == 2

    counts_before = (
        IngestionBatch.objects.count(),
        IngestionRow.objects.count(),
        Job.objects.count(),
    )
    with pytest.raises(ValidationError, match="expired retained source data"):
        _request_and_run_import(
            organization=organization,
            user=user,
            key="retention-late-cross-duplicate",
            payload=payloads[0],
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=import_asset.id,
            monkeypatch=monkeypatch,
        )
    second_cleanup = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    persisted = json.dumps(
        {
            "batches": [
                IngestionBatch.objects.get(pk=batch.pk).input_reference
                for batch in original_batches
            ],
        },
        sort_keys=True,
    )
    assert secret not in persisted
    assert str(import_asset.id) not in persisted
    assert counts_before == (
        IngestionBatch.objects.count(),
        IngestionRow.objects.count(),
        Job.objects.count(),
    )
    assert second_cleanup.redacted == 0
    assert second_cleanup.deleted_text == 0
    assert second_cleanup.anonymized_actors == 0
    assert second_cleanup.no_op == 2


@pytest.mark.django_db
def test_cleanup_tombstones_duplicate_fingerprint_in_every_shared_asset_batch(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="duplicate-cross-batch-document",
    )
    secret = "DUPLICATE-CROSS-BATCH-SECRET"
    payload = {
        "rows": [
            {
                "source_url": "https://example.com/posts/duplicate-cross-batch",
                "original_text": secret,
            }
        ]
    }
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-duplicate-cross-batch-{index}",
            payload=payload,
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=import_asset.id,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence = batches[0].rows.get().source_evidence
    assert batches[1].rows.get().source_evidence_id == evidence.id
    with evidence_service_writes():
        evidence.captured_at = cutoff - timedelta(days=1)
        evidence.save(update_fields=["captured_at", "updated_at"])

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for batch in batches:
        batch.refresh_from_db()
        assert secret not in json.dumps(batch.input_reference, sort_keys=True)
        assert batch.input_reference["retention"]["reason"] == (
            "TRANSIENT_30D_EXPIRED"
        )
    evidence.refresh_from_db()
    assert evidence.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    assert result.redacted == 1
    assert result.protected == 0
    assert result.failures == 0


@pytest.mark.django_db
def test_shared_source_content_transitively_joins_two_asset_components(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    assets = [
        _asset(
            organization=organization,
            user=user,
            marker=f"transitive-asset-{index}",
        )
        for index in (1, 2)
    ]
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-transitive-asset-{index}",
            payload={
                "rows": [
                    {
                        "source_url": f"https://example.com/posts/transitive-{index}",
                        "original_text": f"TRANSITIVE-SECRET-{index}",
                    }
                ]
            },
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=asset.id,
            monkeypatch=monkeypatch,
        )
        for index, asset in enumerate(assets, start=1)
    ]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]
    shared_content = evidence_rows[0].source_signal.source_content
    second_signal = evidence_rows[1].source_signal
    second_signal.source_content = shared_content
    second_signal.save(update_fields=["source_content", "updated_at"])
    second_ingestion_row = batches[1].rows.get()
    second_ingestion_row.source_content = shared_content
    with ingestion_row_service_writes():
        second_ingestion_row.save(update_fields=["source_content", "updated_at"])
    with evidence_service_writes():
        evidence_rows[1].retention_class = SourceEvidence.RetentionClass.CONFIRMED
        evidence_rows[1].save(update_fields=["retention_class", "updated_at"])

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.original_text
    for batch in batches:
        batch.refresh_from_db()
        assert "retention" not in batch.input_reference
    assert result.redacted == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.protected_reasons == {
        "NON_TRANSIENT_RETENTION_CLASS": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_immutable_analysis_reference_protects_every_shared_asset_batch(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="analysis-cross-batch-document",
    )
    batches = [
        _request_and_run_import(
            organization=organization,
            user=user,
            key=f"retention-analysis-cross-batch-{index}",
            payload={
                "rows": [
                    {
                        "source_url": f"https://example.com/posts/analysis-cross-{index}",
                        "original_text": f"ANALYSIS-CROSS-SECRET-{index}",
                    }
                ]
            },
            source_type=IngestionBatch.SourceType.JSON,
            import_asset_id=import_asset.id,
            monkeypatch=monkeypatch,
        )
        for index in (1, 2)
    ]
    evidence_rows = [
        _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
        for batch in batches
    ]
    JobService.create(
        organization=organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot={"evidence_ids": [str(evidence_rows[1].id)]},
        idempotency_key="retention-analysis-cross-batch-snapshot",
        created_by=user,
    )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    for evidence in evidence_rows:
        evidence.refresh_from_db()
        assert evidence.availability == SourceEvidence.Availability.AVAILABLE
        assert evidence.original_text
    assert result.redacted == 0
    assert result.protected == 2
    assert result.failures == 0
    assert result.protected_reasons == {
        "IMMUTABLE_ANALYSIS_REFERENCE": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_new_key_cannot_reuse_tombstoned_screenshot_asset(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    secret_text = "REIMPORT-SECRET need custom helical gear"
    secret_author = "REIMPORT-SECRET-AUTHOR"
    screenshot = _asset(
        organization=organization,
        user=user,
        marker="reimport-secret-screen",
    )
    payload = {
        "source_url": "https://example.com/posts/reimport-retained",
        "original_text": secret_text,
        "author_name": secret_author,
        "screenshot_asset_id": str(screenshot.id),
    }
    first_batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-reimport-first",
        payload=payload,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        monkeypatch=monkeypatch,
    )
    evidence = SourceEvidence.objects.get(
        ingestion_rows__batch=first_batch,
        ingestion_rows__outcome=IngestionRow.Outcome.ACCEPTED,
    )
    with evidence_service_writes():
        evidence.captured_at = cutoff - timedelta(days=1)
        evidence.save(update_fields=["captured_at", "updated_at"])

    first_cleanup = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    assert first_cleanup.redacted == 1

    counts_before = (
        IngestionBatch.objects.count(),
        IngestionRow.objects.count(),
        Job.objects.count(),
    )
    with pytest.raises(ValidationError, match="expired retained source data") as error:
        _request_and_run_import(
            organization=organization,
            user=user,
            key="retention-reimport-second",
            payload=payload,
            source_type=IngestionBatch.SourceType.SCREENSHOT,
            monkeypatch=monkeypatch,
        )
    assert str(screenshot.id) not in str(error.value)
    evidence.refresh_from_db()
    evidence.source_signal.source_content.refresh_from_db()
    committed_after_import = json.dumps(
        {
            "evidence": evidence.original_text,
            "content": {
                "text": evidence.source_signal.source_content.original_text,
                "author": evidence.source_signal.source_content.author_public_name,
            },
            "row": first_batch.rows.get().normalized_input,
            "batch": IngestionBatch.objects.get(pk=first_batch.pk).input_reference,
        },
        sort_keys=True,
    )
    assert secret_text not in committed_after_import
    assert secret_author not in committed_after_import
    assert str(screenshot.id) not in committed_after_import
    assert counts_before == (
        IngestionBatch.objects.count(),
        IngestionRow.objects.count(),
        Job.objects.count(),
    )

    second_cleanup = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    committed_after_cleanup = json.dumps(
        {
            "row": first_batch.rows.get().normalized_input,
            "batch": IngestionBatch.objects.get(pk=first_batch.pk).input_reference,
        },
        sort_keys=True,
    )
    assert secret_text not in committed_after_cleanup
    assert secret_author not in committed_after_cleanup
    assert str(screenshot.id) not in committed_after_cleanup
    assert second_cleanup.redacted == 0
    assert second_cleanup.deleted_text == 0
    assert second_cleanup.anonymized_actors == 0
    assert second_cleanup.no_op == 1


@pytest.mark.django_db
def test_retained_batch_reuses_immutable_original_request_identity(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    source_type = IngestionBatch.SourceType.URL
    payload = {
        "source_url": "https://example.com/posts/retained-identity",
        "original_text": "Original immutable request text",
    }
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retained-request-identity",
        payload=payload,
        source_type=source_type,
        monkeypatch=monkeypatch,
    )
    evidence = SourceEvidence.objects.get(ingestion_rows__batch=batch)
    with evidence_service_writes():
        evidence.captured_at = cutoff - timedelta(days=1)
        evidence.save(update_fields=["captured_at", "updated_at"])
    RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    batch.refresh_from_db()
    original_job_id = batch.job_id
    reference = prepare_import_reference(payload, source_type=source_type)

    reused_batch, reused_job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=source_type,
        idempotency_key="retained-request-identity",
        prepared_reference=reference,
    )

    assert reused_batch.id == batch.id
    assert reused_job.id == original_job_id
    assert IngestionBatch.objects.count() == 1

    changed_reference = prepare_import_reference(
        {
            "source_url": "https://example.com/posts/retained-identity",
            "original_text": "A different request text",
        },
        source_type=source_type,
    )
    with pytest.raises(SourceIdempotencyConflictError):
        SourceIngestionRequestService.create_or_reuse(
            organization=organization,
            creator=user,
            source_type=source_type,
            idempotency_key="retained-request-identity",
            prepared_reference=changed_reference,
        )


@pytest.mark.django_db
def test_original_key_reuses_tombstoned_screenshot_batch_but_new_key_without_asset_is_safe(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    screenshot = _asset(
        organization=organization,
        user=user,
        marker="retained-original-screen",
    )
    payload = {
        "source_url": "https://example.com/posts/retained-original-screen",
        "original_text": "RETAINED-ORIGINAL-SCREEN-TEXT",
        "screenshot_asset_id": str(screenshot.id),
    }
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retained-original-screen",
        payload=payload,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        monkeypatch=monkeypatch,
    )
    evidence = batch.rows.get().source_evidence
    with evidence_service_writes():
        evidence.captured_at = cutoff - timedelta(days=1)
        evidence.save(update_fields=["captured_at", "updated_at"])
    RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    original_job_id = batch.job_id
    original_reference = prepare_import_reference(
        payload,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
    )

    reused_batch, reused_job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        idempotency_key="retained-original-screen",
        prepared_reference=original_reference,
    )
    assert reused_batch.id == batch.id
    assert reused_job.id == original_job_id

    changed_reference = prepare_import_reference(
        {**payload, "original_text": "CHANGED-ORIGINAL-SCREEN-TEXT"},
        source_type=IngestionBatch.SourceType.SCREENSHOT,
    )
    with pytest.raises(SourceIdempotencyConflictError):
        SourceIngestionRequestService.create_or_reuse(
            organization=organization,
            creator=user,
            source_type=IngestionBatch.SourceType.SCREENSHOT,
            idempotency_key="retained-original-screen",
            prepared_reference=changed_reference,
        )
    with pytest.raises(ValidationError, match="expired retained source data"):
        SourceIngestionRequestService.create_or_reuse(
            organization=organization,
            creator=user,
            source_type=IngestionBatch.SourceType.SCREENSHOT,
            idempotency_key="retained-changed-screen-new-key",
            prepared_reference=changed_reference,
        )

    no_asset_reference = prepare_import_reference(
        {
            "rows": [
                {
                    "source_url": payload["source_url"],
                    "original_text": payload["original_text"],
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
    )
    safe_batch, _safe_job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=IngestionBatch.SourceType.JSON,
        idempotency_key="retained-original-without-asset",
        prepared_reference=no_asset_reference,
    )
    assert safe_batch.input_reference["retention"]["reason"] == (
        "TRANSIENT_30D_EXPIRED"
    )


@pytest.mark.django_db
def test_cleanup_protects_evidence_while_matching_raw_import_is_queued(
    organization, user, source_manager, monkeypatch
):
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *_args: None)
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="queued-matching-copy",
        captured_at=cutoff - timedelta(days=1),
        text="Queued raw duplicate",
    )
    reference = prepare_import_reference(
        {
            "source_url": evidence.source_url,
            "original_text": evidence.original_text,
        },
        source_type=IngestionBatch.SourceType.URL,
    )
    batch, _job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=IngestionBatch.SourceType.URL,
        idempotency_key="queued-matching-copy",
        prepared_reference=reference,
    )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    batch.refresh_from_db()
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert evidence.original_text == "Queued raw duplicate"
    assert batch.input_reference["rows"][0]["original_text"] == (
        "Queued raw duplicate"
    )
    assert result.redacted == 0
    assert result.protected == 1
    assert result.protected_reasons == {"SHARED_OR_ACTIVE_RAW_COPY": 1}


@pytest.mark.django_db
def test_active_shared_asset_batch_without_rows_has_specific_protection_reason(
    organization, user, source_manager, monkeypatch
):
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *_args: None)
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="active-empty-shared-import",
    )
    completed = _request_and_run_import(
        organization=organization,
        user=user,
        key="active-empty-shared-completed",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/active-empty-old",
                    "original_text": "ACTIVE-EMPTY-OLD",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    evidence = _make_imported_evidence_old(batch=completed, cutoff=cutoff)[0]
    queued_reference = prepare_import_reference(
        {
            "rows": [
                {
                    "source_url": "https://example.com/posts/active-empty-new",
                    "original_text": "ACTIVE-EMPTY-NEW",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
    )
    queued, _job = SourceIngestionRequestService.create_or_reuse(
        organization=organization,
        creator=user,
        source_type=IngestionBatch.SourceType.JSON,
        idempotency_key="active-empty-shared-queued",
        prepared_reference=queued_reference,
        import_asset_id=import_asset.id,
    )
    assert not queued.rows.exists()

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.protected_reasons == {"SHARED_RAW_GROUP_ACTIVE": 1}


@pytest.mark.django_db
def test_cleanup_rolls_back_every_copy_when_batch_tombstone_fails(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    secret_text = "ROLLBACK-SECRET-TEXT"
    secret_author = "ROLLBACK-SECRET-AUTHOR"
    screenshot = _asset(
        organization=organization,
        user=user,
        marker="rollback-screen",
    )
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="rollback-copy",
        captured_at=cutoff - timedelta(days=1),
        text=secret_text,
        screenshot_asset=screenshot,
    )
    content = evidence.source_signal.source_content
    content.author_public_name = secret_author
    content.save(update_fields=["author_public_name", "updated_at"])
    batch, row = _attach_ingestion_copy(
        evidence=evidence,
        user=user,
        author_name=secret_author,
        screenshot_asset=screenshot,
    )

    def fail_batch_tombstone(*_args, **_kwargs):
        raise ValidationError("simulated batch tombstone failure")

    monkeypatch.setattr(
        IngestionBatchQuerySet,
        "_service_tombstone_input_reference",
        fail_batch_tombstone,
    )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    content.refresh_from_db()
    batch.refresh_from_db()
    row.refresh_from_db()
    assert evidence.original_text == secret_text
    assert evidence.screenshot_asset_id == screenshot.id
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert content.original_text == secret_text
    assert content.author_public_name == secret_author
    assert row.normalized_input["original_text"] == secret_text
    assert batch.input_reference["rows"][0]["original_text"] == secret_text
    assert result.redacted == 0
    assert result.failures == 1
    assert result.deleted_text == 0
    assert result.anonymized_actors == 0


@pytest.mark.django_db
def test_cleanup_redacted_evidence_still_tombstones_later_linked_raw_copies(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    secret_text = "LATE-LINKED-RAW-COPY"
    secret_author = "LATE-LINKED-AUTHOR"
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="late-linked-copy",
        captured_at=cutoff - timedelta(days=1),
        text=secret_text,
    )
    first = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )
    assert first.redacted == 1
    reference = prepare_import_reference(
        {
            "source_url": evidence.source_url,
            "original_text": secret_text,
            "author_name": secret_author,
        },
        source_type=IngestionBatch.SourceType.URL,
    )
    batch = IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.URL,
        input_reference=reference,
        idempotency_key="late-linked-raw-copy",
        created_by=user,
    )
    with ingestion_row_service_writes():
        row = IngestionRow.objects.create(
            organization=organization,
            batch=batch,
            row_number=1,
            normalized_input={
                key: value
                for key, value in reference["rows"][0].items()
                if key != "row_number"
            },
            outcome=IngestionRow.Outcome.DUPLICATE,
            source_content=evidence.source_signal.source_content,
            source_signal=evidence.source_signal,
            source_evidence=evidence,
        )

    second = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    batch.refresh_from_db()
    row.refresh_from_db()
    persisted = json.dumps(
        {"batch": batch.input_reference, "row": row.normalized_input},
        sort_keys=True,
    )
    assert secret_text not in persisted
    assert secret_author not in persisted
    assert row.normalized_input["retention"]["source_evidence_id"] == str(
        evidence.id
    )
    assert second.redacted == 0
    assert second.deleted_text == 2
    assert second.anonymized_actors == 2
    assert second.no_op == 0


@pytest.mark.django_db
def test_cleanup_treats_exact_cutoff_as_not_older(organization, user, source_manager):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="boundary",
        captured_at=cutoff,
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    assert evidence.original_text
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.no_op == 1


@pytest.mark.django_db
def test_cleanup_keeps_confirmed_handoff_reviewed_and_active_analysis_evidence(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    confirmed = _evidence(
        organization=organization,
        user=user,
        marker="confirmed",
        captured_at=cutoff - timedelta(days=1),
        retention_class=SourceEvidence.RetentionClass.CONFIRMED,
    )
    handoff = _evidence(
        organization=organization,
        user=user,
        marker="handoff",
        captured_at=cutoff - timedelta(days=1),
        retention_class=SourceEvidence.RetentionClass.HANDOFF_PROTECTED,
    )
    reviewed = _evidence(
        organization=organization,
        user=user,
        marker="reviewed",
        captured_at=cutoff - timedelta(days=1),
    )
    candidate = LeadService.create_candidate(
        organization=organization,
        creator=user,
        company_name="Reviewed GmbH",
        company_domain="reviewed.example",
        country_hint="DE",
        evidence_ids=[reviewed.id],
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE leads_leadcandidate SET status = %s WHERE id = %s",
            [LeadCandidate.Status.REVIEWED, candidate.id.hex],
        )
    ready = _evidence(
        organization=organization,
        user=user,
        marker="ready-handoff",
        captured_at=cutoff - timedelta(days=1),
    )
    ready_candidate = LeadService.create_candidate(
        organization=organization,
        creator=user,
        company_name="Ready GmbH",
        company_domain="ready.example",
        country_hint="DE",
        evidence_ids=[ready.id],
    )
    handed = _evidence(
        organization=organization,
        user=user,
        marker="handed-off",
        captured_at=cutoff - timedelta(days=1),
    )
    handed_candidate = LeadService.create_candidate(
        organization=organization,
        creator=user,
        company_name="Handed GmbH",
        company_domain="handed.example",
        country_hint="DE",
        evidence_ids=[handed.id],
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE leads_leadcandidate SET status = %s WHERE id = %s",
            [LeadCandidate.Status.READY_FOR_HANDOFF, ready_candidate.id.hex],
        )
        cursor.execute(
            "UPDATE leads_leadcandidate SET status = %s WHERE id = %s",
            [LeadCandidate.Status.HANDED_OFF, handed_candidate.id.hex],
        )
    active = _evidence(
        organization=organization,
        user=user,
        marker="active",
        captured_at=cutoff - timedelta(days=1),
    )
    JobService.create(
        organization=organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot={
            "schema": "LEAD_ANALYSIS_INPUT_V1",
            "organization_id": str(organization.id),
            "evidence": [{"id": str(active.id)}],
        },
        idempotency_key="active-retention-protection",
        created_by=user,
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    for row in (confirmed, handoff, reviewed, ready, handed, active):
        row.refresh_from_db()
        assert row.original_text
        assert row.availability == SourceEvidence.Availability.AVAILABLE
    assert result.protected == 6
    assert result.redacted == 0
    assert result.protected_reasons == {
        "IMMUTABLE_ANALYSIS_REFERENCE": 1,
        "NON_TRANSIENT_RETENTION_CLASS": 2,
        "REVIEW_OR_HANDOFF_STATE": 3,
    }


@pytest.mark.django_db
def test_cleanup_protects_unknown_future_retention_class_by_default(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="future-retention",
        captured_at=cutoff - timedelta(days=1),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_sourceevidence SET retention_class = %s WHERE id = %s",
            ["LEGAL_HOLD", evidence.id.hex],
        )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    assert evidence.original_text
    assert evidence.retention_class == "LEGAL_HOLD"
    assert result.protected == 1
    assert result.failures == 0
    assert result.protected_reasons == {
        "NON_TRANSIENT_RETENTION_CLASS": 1,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("snapshot_owner", ["JOB", "AI_RUN"])
def test_cleanup_protects_completed_immutable_analysis_snapshots(
    organization, user, source_manager, snapshot_owner
):
    cutoff = timezone.now() - timedelta(days=30)
    secret = f"immutable completed analysis secret {snapshot_owner}"
    evidence = _evidence(
        organization=organization,
        user=user,
        marker=f"completed-{snapshot_owner.lower()}",
        captured_at=cutoff - timedelta(days=1),
        text=secret,
    )
    frozen = canonical_source_evidence_snapshot(
        evidence,
        organization=organization,
    )
    job_snapshot = {"evidence": [frozen]} if snapshot_owner == "JOB" else {"other": True}
    job = JobService.create(
        organization=organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot=job_snapshot,
        idempotency_key=f"completed-analysis-{snapshot_owner.lower()}",
        created_by=user,
    )
    claimed = JobService.claim(
        worker_id="completed-analysis-test",
        job_id=job.id,
        job_type=Job.Type.LEAD_ANALYZE,
    )
    JobService.succeed(job.id, claim_token=claimed.claim_token, result_reference={})
    if snapshot_owner == "AI_RUN":
        prompt = PromptVersionService.create(
            purpose="LEAD_ANALYZE",
            code="retention-completed-ai-run",
            provider="fake",
            model="fake-v1",
            template="Analyze.",
            output_schema={"type": "object"},
            status=PromptVersion.Status.PUBLISHED,
            created_by=user,
        )
        with ai_audit_writes():
            AIRun.objects.create(
                organization=organization,
                job=job,
                job_attempt=1,
                prompt_version=prompt,
                provider="fake",
                model="fake-v1",
                input_snapshot={"evidence": [frozen]},
                status=AIRun.Status.SUCCEEDED,
                output_json={},
                started_at=timezone.now(),
                finished_at=timezone.now(),
            )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    assert evidence.original_text == secret
    assert result.protected == 1
    assert result.redacted == 0
    assert result.deleted_text == 0
    assert result.protected_reasons == {
        "IMMUTABLE_ANALYSIS_REFERENCE": 1,
    }


@pytest.mark.django_db
def test_cleanup_keeps_evidence_referenced_by_confirm_review_history(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="review-history",
        captured_at=cutoff - timedelta(days=1),
    )
    candidate = LeadService.create_candidate(
        organization=organization,
        creator=user,
        company_name="Historical Review Ltd",
        company_domain="historical-review.example",
        country_hint="GB",
        evidence_ids=[evidence.id],
    )
    with lead_history_writes():
        LeadReview.objects.create(
            organization=organization,
            candidate=candidate,
            action=LeadReview.Action.CONFIRM,
            reason="Human confirmed the public trace.",
            reviewer=user,
            idempotency_key="retention-confirm-history",
            intent_hash="f" * 64,
            candidate_status=LeadCandidate.Status.REVIEWED,
            candidate_version=candidate.version,
        )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    assert evidence.original_text
    assert result.protected == 1
    assert result.redacted == 0
    assert result.protected_reasons == {"HUMAN_REVIEW_HISTORY": 1}


@pytest.mark.django_db
def test_cleanup_does_not_anonymize_source_shared_with_protected_evidence(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    transient = _evidence(
        organization=organization,
        user=user,
        marker="shared-source",
        captured_at=cutoff - timedelta(days=1),
    )
    protected = EvidenceService.create(
        organization=organization,
        signal=transient.source_signal,
        original_text="Confirmed requirement on the same source",
        source_url="https://example.com/posts/shared-source?confirmed=1",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.PASTE,
        public_published_at=cutoff - timedelta(days=1),
        created_by=user,
    )
    with evidence_service_writes():
        protected.captured_at = cutoff - timedelta(days=1)
        protected.retention_class = SourceEvidence.RetentionClass.CONFIRMED
        protected.save(
            update_fields=["captured_at", "retention_class", "updated_at"]
        )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    transient.refresh_from_db()
    protected.refresh_from_db()
    transient.source_signal.source_content.refresh_from_db()
    assert transient.original_text
    assert protected.original_text
    assert transient.source_signal.source_content.author_public_name
    assert transient.source_signal.source_content.original_text
    assert result.redacted == 0
    assert result.protected == 2
    assert result.anonymized_actors == 0
    assert result.protected_reasons == {
        "NON_TRANSIENT_RETENTION_CLASS": 1,
        "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE": 1,
    }


@pytest.mark.django_db
def test_cleanup_redacts_all_expired_evidence_that_share_source_content_idempotently(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    first = _evidence(
        organization=organization,
        user=user,
        marker="same-content-expired",
        captured_at=cutoff - timedelta(days=1),
    )
    second = EvidenceService.create(
        organization=organization,
        signal=first.source_signal,
        original_text="Second evidence copy on the same content",
        source_url="https://example.com/posts/same-content-expired?copy=2",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.PASTE,
        public_published_at=cutoff - timedelta(days=1),
        created_by=user,
    )
    with evidence_service_writes():
        second.captured_at = cutoff - timedelta(days=1)
        second.save(update_fields=["captured_at", "updated_at"])

    first_result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )
    second_result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    first.refresh_from_db()
    second.refresh_from_db()
    first.source_signal.source_content.refresh_from_db()
    assert first.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    assert second.availability == SourceEvidence.Availability.REDACTED_BY_RETENTION
    assert first.source_signal.source_content.original_text == ""
    assert first.source_signal.source_content.author_public_name == ""
    assert first_result.redacted == 2
    assert first_result.protected == 0
    assert first_result.failures == 0
    assert second_result.redacted == 0
    assert second_result.no_op == 2


@pytest.mark.django_db
def test_cleanup_reads_analysis_history_once_under_organization_lock(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="analysis-race",
        captured_at=cutoff - timedelta(days=1),
    )
    reads = []

    def read_once(**_kwargs):
        reads.append(True)
        return {str(evidence.id)}

    monkeypatch.setattr(
        RetentionService,
        "_active_analysis_evidence_ids",
        read_once,
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    assert evidence.original_text
    assert result.protected == 1
    assert result.redacted == 0
    assert reads == [True]


@pytest.mark.django_db
def test_cleanup_history_snapshot_scans_are_constant_for_one_or_many_evidence(
    organization, other_organization, user
):
    cutoff = timezone.now() - timedelta(days=30)

    def run_for(*, scope, actor_name, count):
        actor = get_user_model().objects.create_user(username=actor_name)
        Membership.objects.create(
            user=actor,
            organization=scope,
            role=Role.objects.create_operator(),
        )
        for index in range(count):
            _evidence(
                organization=scope,
                user=user,
                marker=f"history-query-{actor_name}-{index}",
                captured_at=cutoff - timedelta(days=1),
            )
        with CaptureQueriesContext(connection) as queries:
            RetentionService.cleanup(
                organization=scope,
                cutoff=cutoff,
                actor=actor,
            )
        history_queries = [
            query["sql"]
            for query in queries.captured_queries
            if (
                'SELECT "jobs_job"."input_snapshot"' in query["sql"]
                or 'SELECT "ai_airun"."input_snapshot"' in query["sql"]
            )
        ]
        return len(history_queries)

    one = run_for(scope=organization, actor_name="history-one", count=1)
    many = run_for(
        scope=other_organization,
        actor_name="history-many",
        count=8,
    )

    assert one == many == 2


@pytest.mark.django_db
def test_analysis_history_snapshots_use_two_bounded_streaming_iterators(
    organization, monkeypatch
):
    observed = []
    original_iterator = QuerySet.iterator

    def observe_iterator(queryset, *args, **kwargs):
        if queryset.model in {Job, AIRun}:
            observed.append((queryset.model, kwargs.get("chunk_size")))
        return original_iterator(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "iterator", observe_iterator)

    RetentionService._active_analysis_evidence_ids(organization=organization)

    assert [model for model, _chunk_size in observed] == [Job, AIRun]
    assert all(
        isinstance(chunk_size, int) and 1 <= chunk_size <= 1000
        for _model, chunk_size in observed
    )


@pytest.mark.django_db
def test_retention_component_discovery_has_constant_query_count(
    organization, other_organization, user
):
    cutoff = timezone.now() - timedelta(days=30)

    def discover(*, scope, count):
        evidence_ids = [
            _evidence(
                organization=scope,
                user=user,
                marker=f"component-query-{scope.id}-{index}",
                captured_at=cutoff - timedelta(days=1),
            ).id
            for index in range(count)
        ]
        with CaptureQueriesContext(connection) as queries:
            components = RetentionService._retention_components(
                organization=scope,
                candidate_ids=evidence_ids,
            )
        return len(queries), len(components)

    one_queries, one_components = discover(scope=organization, count=1)
    many_queries, many_components = discover(scope=other_organization, count=8)

    assert one_queries == many_queries
    assert one_components == 1
    assert many_components == 8


@pytest.mark.django_db
def test_retention_component_discovery_returns_before_loading_history_when_empty(
    organization,
):
    with CaptureQueriesContext(connection) as queries:
        components = RetentionService._retention_components(
            organization=organization,
            candidate_ids=[],
        )

    assert components == []
    assert len(queries) == 0


@pytest.mark.django_db
def test_shared_asset_component_discovery_queries_are_constant_across_batch_count(
    organization, other_organization, user, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)

    def discover(*, scope, marker, count):
        import_asset = _asset(
            organization=scope,
            user=user,
            marker=f"component-shared-asset-{marker}",
        )
        evidence_ids = []
        for index in range(count):
            batch = _request_and_run_import(
                organization=scope,
                user=user,
                key=f"retention-component-shared-{marker}-{index}",
                payload={
                    "rows": [
                        {
                            "source_url": (
                                f"https://example.com/posts/component-shared-"
                                f"{marker}-{index}"
                            ),
                            "original_text": f"COMPONENT-SHARED-{marker}-{index}",
                        }
                    ]
                },
                source_type=IngestionBatch.SourceType.JSON,
                import_asset_id=import_asset.id,
                monkeypatch=monkeypatch,
            )
            evidence_ids.extend(
                evidence.id
                for evidence in _make_imported_evidence_old(
                    batch=batch,
                    cutoff=cutoff,
                )
            )
        with CaptureQueriesContext(connection) as queries:
            components = RetentionService._retention_components(
                organization=scope,
                candidate_ids=evidence_ids,
            )
        return len(queries), components

    one_queries, one_components = discover(
        scope=organization,
        marker="one",
        count=1,
    )
    many_queries, many_components = discover(
        scope=other_organization,
        marker="many",
        count=8,
    )

    assert one_queries == many_queries
    assert len(one_components) == len(many_components) == 1
    assert len(one_components[0].asset_batch_ids) == 1
    assert len(many_components[0].asset_batch_ids) == 8


@pytest.mark.django_db
def test_cleanup_locks_organization_then_batch_evidence_and_ingestion_rows(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-lock-order",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/lock-order",
                    "original_text": "LOCK-ORDER-RAW",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        monkeypatch=monkeypatch,
    )
    _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    locked_models = []
    original_fetch_all = QuerySet._fetch_all

    def observe_locked_fetch(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        return original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", observe_locked_fetch)

    RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    first_positions = {
        model: locked_models.index(model)
        for model in (Organization, IngestionBatch, SourceEvidence, IngestionRow)
    }
    assert first_positions[Organization] < first_positions[IngestionBatch]
    assert first_positions[IngestionBatch] < first_positions[SourceEvidence]
    assert first_positions[SourceEvidence] < first_positions[IngestionRow]


@pytest.mark.django_db
def test_shared_asset_cleanup_locks_asset_before_batches_evidence_and_rows(
    organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    import_asset = _asset(
        organization=organization,
        user=user,
        marker="shared-asset-lock-order",
    )
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="retention-shared-asset-lock-order",
        payload={
            "rows": [
                {
                    "source_url": "https://example.com/posts/shared-asset-lock-order",
                    "original_text": "SHARED-ASSET-LOCK-ORDER-RAW",
                }
            ]
        },
        source_type=IngestionBatch.SourceType.JSON,
        import_asset_id=import_asset.id,
        monkeypatch=monkeypatch,
    )
    _make_imported_evidence_old(batch=batch, cutoff=cutoff)
    locked_models = []
    original_fetch_all = QuerySet._fetch_all

    def observe_locked_fetch(queryset):
        if queryset._result_cache is None and queryset.query.select_for_update:
            locked_models.append(queryset.model)
        return original_fetch_all(queryset)

    monkeypatch.setattr(QuerySet, "_fetch_all", observe_locked_fetch)

    RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    first_positions = {
        model: locked_models.index(model)
        for model in (
            Organization,
            MaterialAsset,
            IngestionBatch,
            SourceEvidence,
            IngestionRow,
        )
    }
    assert first_positions[Organization] < first_positions[MaterialAsset]
    assert first_positions[MaterialAsset] < first_positions[IngestionBatch]
    assert first_positions[IngestionBatch] < first_positions[SourceEvidence]
    assert first_positions[SourceEvidence] < first_positions[IngestionRow]


@pytest.mark.django_db
def test_cleanup_ignores_unbound_malformed_active_snapshot_without_crashing(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="malformed-active",
        captured_at=cutoff - timedelta(days=1),
    )
    JobService.create(
        organization=organization,
        job_type=Job.Type.LEAD_ANALYZE,
        input_snapshot={"evidence_ids": None, "evidence": "not-a-list"},
        idempotency_key="malformed-active-analysis",
        created_by=user,
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    assert evidence.original_text == ""
    assert result.redacted == 1


@pytest.mark.django_db
def test_cleanup_is_idempotent_and_does_not_duplicate_audit(
    organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="twice",
        captured_at=cutoff - timedelta(days=1),
    )

    first = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )
    second = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    assert first.redacted == 1
    assert second.redacted == 0
    assert second.deleted_text == 0
    assert second.anonymized_actors == 0
    assert second.no_op == 1
    audits = AuditLog.objects.filter(
        organization=organization,
        object_type="sources.RetentionCleanup",
    )
    assert audits.count() == 1
    audit = audits.get()
    assert audit.actor == source_manager
    serialized = json.dumps(audit.after_metadata, ensure_ascii=False)
    assert str(evidence.id) in serialized
    assert "Private public trace twice" not in serialized
    assert "Public Person twice" not in serialized


@pytest.mark.django_db
def test_cleanup_isolates_organizations(
    organization, other_organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    own = _evidence(
        organization=organization,
        user=user,
        marker="own",
        captured_at=cutoff - timedelta(days=1),
    )
    foreign = _evidence(
        organization=other_organization,
        user=user,
        marker="foreign",
        captured_at=cutoff - timedelta(days=1),
    )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.original_text == ""
    assert foreign.original_text
    assert result.redacted == 1
    assert result.protected == 0
    assert result.failures == 0


@pytest.mark.django_db
def test_cleanup_leaves_inconsistent_row_atomic_and_counts_failure(
    organization, other_organization, user, source_manager
):
    cutoff = timezone.now() - timedelta(days=30)
    own_asset = _asset(organization=organization, user=user, marker="atomic-own")
    foreign_asset = _asset(
        organization=other_organization, user=user, marker="atomic-foreign"
    )
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="atomic",
        captured_at=cutoff - timedelta(days=1),
        translated_text="translated sensitive text",
        screenshot_asset=own_asset,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_sourceevidence SET screenshot_asset_id = %s WHERE id = %s",
            [foreign_asset.id.hex, evidence.id.hex],
        )

    result = RetentionService.cleanup(
        organization=organization, cutoff=cutoff, actor=source_manager
    )

    evidence.refresh_from_db()
    assert evidence.original_text
    assert evidence.translated_text
    assert evidence.screenshot_asset_id == foreign_asset.id
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.failures == 1


@pytest.mark.django_db
def test_cleanup_fails_closed_after_raw_screenshot_identity_drift(
    organization, other_organization, user, source_manager, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    own_asset = _asset(
        organization=organization,
        user=user,
        marker="row-identity-own",
    )
    foreign_asset = _asset(
        organization=other_organization,
        user=user,
        marker="row-identity-foreign",
    )
    batch = _request_and_run_import(
        organization=organization,
        user=user,
        key="row-identity-raw-drift",
        payload={
            "source_url": "https://example.com/posts/row-identity-drift",
            "original_text": "ROW-IDENTITY-DRIFT-SECRET",
            "screenshot_asset_id": str(own_asset.id),
        },
        source_type=IngestionBatch.SourceType.SCREENSHOT,
        monkeypatch=monkeypatch,
    )
    evidence = _make_imported_evidence_old(batch=batch, cutoff=cutoff)[0]
    row = batch.rows.get()
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sources_ingestionrow "
            "SET request_screenshot_asset_id = %s WHERE id = %s",
            [foreign_asset.id.hex, row.id.hex],
        )

    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=source_manager,
    )

    evidence.refresh_from_db()
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert evidence.original_text == "ROW-IDENTITY-DRIFT-SECRET"
    assert result.redacted == 0
    assert result.protected == 1
    assert result.protected_reasons == {"SHARED_IMPORT_ASSET_INCONSISTENT": 1}


@pytest.mark.django_db
def test_cleanup_requires_source_management_for_human_actor(organization, user):
    cutoff = timezone.now() - timedelta(days=30)
    reviewer = get_user_model().objects.create_user(username="retention-reviewer")
    read_only = Role.objects.create_read_only()
    Membership.objects.create(
        user=reviewer,
        organization=organization,
        role=read_only,
    )

    with pytest.raises(PermissionDenied, match="sources.manage"):
        RetentionService.cleanup(
            organization=organization,
            cutoff=cutoff,
            actor=reviewer,
        )

    operator = get_user_model().objects.create_user(username="retention-operator")
    operator_role = Role.objects.create_operator()
    Membership.objects.create(
        user=operator,
        organization=organization,
        role=operator_role,
    )
    result = RetentionService.cleanup(
        organization=organization,
        cutoff=cutoff,
        actor=operator,
    )
    assert result.redacted == 0


@pytest.mark.django_db
def test_direct_cleanup_rejects_null_actor(organization):
    with pytest.raises(PermissionDenied, match="system path"):
        RetentionService.cleanup(
            organization=organization,
            cutoff=timezone.now() - timedelta(days=30),
            actor=None,
        )

    with pytest.raises(PermissionDenied, match="claimed retention job"):
        RetentionService.cleanup_owned(
            organization=organization,
            cutoff=timezone.now() - timedelta(days=30),
            actor=None,
            job_id=None,
            claim_token=None,
        )


@pytest.mark.django_db
def test_cleanup_rejects_naive_cutoff(organization, source_manager):
    with pytest.raises(ValueError, match="timezone-aware"):
        RetentionService.cleanup(
            organization=organization,
            cutoff=timezone.now().replace(tzinfo=None),
            actor=source_manager,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("cutoff", [None, "2026-07-11T00:00:00+00:00"])
def test_cleanup_rejects_non_datetime_cutoff(
    organization, source_manager, cutoff
):
    with pytest.raises(ValueError, match="timezone-aware datetime"):
        RetentionService.cleanup(
            organization=organization,
            cutoff=cutoff,
            actor=source_manager,
        )
