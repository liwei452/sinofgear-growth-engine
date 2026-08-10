import hashlib
import json

import pytest
from django.core.exceptions import ValidationError

from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.sources.importers import prepare_import_reference
from apps.sources.models import (
    IngestionBatch,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from apps.sources.services import EvidenceService


pytestmark = pytest.mark.django_db


def _create_evidence(*, organization, user, marker="api", asset=None):
    target = MonitoringTarget.objects.create(
        organization=organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.MANUAL_URL,
        platform="MANUAL",
        normalized_url=f"https://e.test/{marker}",
        label=f"Target {marker}",
        created_by=user,
    )
    content = SourceContent.objects.create(
        organization=organization,
        monitoring_target=target,
        platform="MANUAL",
        canonical_url=f"https://e.test/{marker}",
        original_text=f"Need gear {marker}",
        content_hash=(marker.encode().hex() + "0" * 64)[:64],
        created_by=user,
    )
    signal = SourceSignal.objects.create(
        organization=organization,
        monitoring_target=target,
        source_content=content,
        signal_type=SourceSignal.SignalType.MENTION,
        platform="MANUAL",
        created_by=user,
    )
    return EvidenceService.create(
        organization=organization,
        signal=signal,
        original_text=f"Need gear {marker}",
        source_url=f"https://e.test/{marker}",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.URL,
        public_published_at=None,
        created_by=user,
        screenshot_asset=asset,
    )


def test_create_monitoring_target_and_list_are_organization_scoped(
    operator_member_client, other_organization, user
):
    _member, client = operator_member_client
    MonitoringTarget.objects.create(
        organization=other_organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.MANUAL_URL,
        platform="OTHER",
        normalized_url="https://other.test/private",
        label="Other private target",
        created_by=user,
    )

    created = client.post(
        "/api/v1/monitoring-targets",
        {
            "target_type": "POST",
            "collection_mode": "MANUAL_URL",
            "platform": "MANUAL",
            "normalized_url": "https://Example.com:443/posts/1#x",
            "label": "Gear request",
        },
        format="json",
    )
    listed = client.get("/api/v1/monitoring-targets")

    assert created.status_code == 201
    assert created.json()["normalized_url"] == "https://example.com/posts/1"
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["results"]] == [created.json()["id"]]


@pytest.mark.parametrize(
    "path",
    ["/api/v1/monitoring-targets", "/api/v1/ingestion-batches"],
)
def test_source_mutation_validation_errors_render_recovery_envelope(
    path, operator_member_client
):
    _member, client = operator_member_client

    response = client.post(path, {}, format="json")

    assert response.status_code == 400
    assert set(response.json()) >= {"code", "message", "recovery_action"}


def test_create_paste_batch_returns_202_job_reference_and_persists_only_prepared_input(
    operator_member_client, monkeypatch, django_capture_on_commit_callbacks
):
    member, client = operator_member_client
    queued = []
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *args: queued.append(args))

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/v1/ingestion-batches",
            {
                "source_type": "PASTE",
                "idempotency_key": "paste-20260810-1",
                "payload": {
                    "text": "https://example.com/p/1\tWe need 200 replacement gears",
                    "authorization": "Bearer raw-secret",
                    "unknown": {"cookie": "session=raw-secret"},
                },
            },
            format="json",
        )

    assert response.status_code == 202
    assert set(response.json()) == {"job_id", "ingestion_batch_id", "status"}
    batch = IngestionBatch.objects.select_related("job").get(pk=response.json()["ingestion_batch_id"])
    assert batch.created_by == member
    assert set(batch.input_reference) == {"schema", "source_type", "rows", "errors"}
    assert batch.input_reference["rows"][0]["original_text"] == (
        "We need 200 replacement gears"
    )
    persisted = json.dumps(
        {"batch": batch.input_reference, "job": batch.job.input_snapshot}, sort_keys=True
    )
    assert "raw-secret" not in persisted
    prepared_digest = hashlib.sha256(
        json.dumps(
            batch.input_reference,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert batch.job.input_snapshot == {
        "schema": "SOURCE_IMPORT_JOB_V1",
        "ingestion_batch_id": str(batch.id),
        "source_type": "PASTE",
        "monitoring_target_id": None,
        "prepared_reference_sha256": prepared_digest,
        "import_asset_id": None,
        "batch_idempotency_key": "paste-20260810-1",
    }
    assert "input_reference" not in batch.job.input_snapshot
    assert "rows" not in json.dumps(batch.job.input_snapshot, sort_keys=True)
    assert queued == [(str(batch.job_id), str(batch.id))]


def test_same_idempotency_key_and_prepared_payload_reuses_batch_job_without_requeue(
    operator_member_client, monkeypatch, django_capture_on_commit_callbacks
):
    _member, client = operator_member_client
    queued = []
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *args: queued.append(args))
    request = {
        "source_type": "JSON",
        "idempotency_key": "same-json-key",
        "payload": {
            "rows": [{"source_url": "https://e.test/idempotent", "original_text": "Need gear"}]
        },
    }

    with django_capture_on_commit_callbacks(execute=True):
        first = client.post("/api/v1/ingestion-batches", request, format="json")
        second = client.post("/api/v1/ingestion-batches", request, format="json")

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert IngestionBatch.objects.count() == 1
    assert queued == [
        (first.json()["job_id"], first.json()["ingestion_batch_id"]),
    ]


def test_same_idempotency_key_with_different_prepared_payload_returns_safe_409(
    operator_member_client,
):
    _member, client = operator_member_client
    base = {"source_type": "PASTE", "idempotency_key": "conflicting-key"}

    first = client.post(
        "/api/v1/ingestion-batches",
        {**base, "payload": {"text": "https://e.test/one\tFirst public value"}},
        format="json",
    )
    conflict = client.post(
        "/api/v1/ingestion-batches",
        {**base, "payload": {"text": "https://e.test/two\tSecond private value"}},
        format="json",
    )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert set(conflict.json()) >= {"code", "message", "recovery_action"}
    assert "Second private value" not in json.dumps(conflict.json())
    assert IngestionBatch.objects.count() == 1


def test_preexisting_unbound_source_job_is_rejected_without_enqueue(
    operator_member_client, organization, monkeypatch, django_capture_on_commit_callbacks
):
    member, client = operator_member_client
    key = "existing-matching-job"
    payload = {"text": "https://e.test/existing\tNeed gear"}
    reference = prepare_import_reference(payload, source_type="PASTE")
    existing_job = JobService.create(
        organization=organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={
            "source_type": "PASTE",
            "monitoring_target_id": None,
            "input_reference": reference,
        },
        idempotency_key=key,
        created_by=member,
    )
    queued = []
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *args: queued.append(args))

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/api/v1/ingestion-batches",
            {"source_type": "PASTE", "idempotency_key": key, "payload": payload},
            format="json",
        )

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_conflict"
    assert Job.objects.filter(pk=existing_job.id).exists()
    assert IngestionBatch.objects.count() == 0
    assert queued == []


def test_preexisting_conflicting_source_job_returns_409_and_rolls_back_batch(
    operator_member_client, organization
):
    member, client = operator_member_client
    key = "existing-conflicting-job"
    JobService.create(
        organization=organization,
        job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"source_type": "PASTE", "input_reference": {"safe": "different"}},
        idempotency_key=key,
        created_by=member,
    )

    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "PASTE",
            "idempotency_key": key,
            "payload": {"text": "https://e.test/conflict\tNeed gear"},
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_conflict"
    assert IngestionBatch.objects.count() == 0


def test_existing_batch_bound_to_non_source_job_is_rejected_as_conflict(
    operator_member_client, organization
):
    member, client = operator_member_client
    key = "wrong-bound-job"
    payload = {"text": "https://e.test/wrong-bound\tNeed gear"}
    reference = prepare_import_reference(payload, source_type="PASTE")
    wrong_job = JobService.create(
        organization=organization,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={"safe": "unrelated"},
        idempotency_key=key,
        created_by=member,
    )
    IngestionBatch.objects.create(
        organization=organization,
        source_type=IngestionBatch.SourceType.PASTE,
        input_reference=reference,
        idempotency_key=key,
        job=wrong_job,
        created_by=member,
    )

    response = client.post(
        "/api/v1/ingestion-batches",
        {"source_type": "PASTE", "idempotency_key": key, "payload": payload},
        format="json",
    )

    assert response.status_code == 409
    assert response.json()["code"] == "idempotency_conflict"


def test_repeated_running_and_terminal_job_requests_do_not_requeue(
    operator_member_client, monkeypatch, django_capture_on_commit_callbacks
):
    _member, client = operator_member_client
    queued = []
    from apps.sources import tasks

    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *args: queued.append(args))
    request = {
        "source_type": "PASTE",
        "idempotency_key": "status-stable-key",
        "payload": {"text": "https://e.test/status\tNeed gear"},
    }
    with django_capture_on_commit_callbacks(execute=True):
        created = client.post("/api/v1/ingestion-batches", request, format="json")
    claimed = JobService.claim(worker_id="test-status-worker", job_id=created.json()["job_id"])

    with django_capture_on_commit_callbacks(execute=True):
        running = client.post("/api/v1/ingestion-batches", request, format="json")
    JobService.succeed(
        claimed.id,
        claim_token=claimed.claim_token,
        result_reference={"ingestion_batch_id": created.json()["ingestion_batch_id"]},
    )
    with django_capture_on_commit_callbacks(execute=True):
        terminal = client.post("/api/v1/ingestion-batches", request, format="json")

    assert created.json() == running.json() == terminal.json()
    assert queued == [(created.json()["job_id"], created.json()["ingestion_batch_id"])]


def test_job_creation_failure_rolls_back_batch_and_registers_no_on_commit_work(
    operator_member_client, monkeypatch, django_capture_on_commit_callbacks
):
    _member, client = operator_member_client
    from apps.sources import tasks

    queued = []
    monkeypatch.setattr(tasks.execute_source_import, "delay", lambda *args: queued.append(args))

    def fail_job_create(**_kwargs):
        raise ValidationError("Unable to create the import job.")

    monkeypatch.setattr(JobService, "create", fail_job_create)
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = client.post(
            "/api/v1/ingestion-batches",
            {
                "source_type": "PASTE",
                "idempotency_key": "rolled-back-job",
                "payload": {"text": "https://e.test/rollback\tNeed gear"},
            },
            format="json",
        )

    assert response.status_code == 400
    assert IngestionBatch.objects.count() == 0
    assert callbacks == []
    assert queued == []


def test_ingestion_request_rejects_unknown_top_level_fields_without_persistence(
    operator_member_client,
):
    _member, client = operator_member_client

    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "PASTE",
            "idempotency_key": "unknown-top-level",
            "payload": {"text": "https://e.test/strict\tNeed gear"},
            "connector_credentials": {"password": "raw-secret"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert "raw-secret" not in json.dumps(response.json())
    assert IngestionBatch.objects.count() == 0


def test_active_owned_import_asset_is_the_only_asset_reference_persisted(
    operator_member_client, asset
):
    _member, client = operator_member_client

    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "JSON",
            "import_asset_id": str(asset.id),
            "idempotency_key": "owned-import-asset",
            "payload": {
                "rows": [
                    {
                        "source_url": "https://e.test/import-asset",
                        "original_text": "Need gear",
                        "storage_key": "raw/private/storage-key",
                    }
                ]
            },
        },
        format="json",
    )

    assert response.status_code == 202
    batch = IngestionBatch.objects.get(pk=response.json()["ingestion_batch_id"])
    assert batch.input_reference["import_asset_id"] == str(asset.id)
    assert "storage_key" not in json.dumps(batch.input_reference)


def test_source_collection_lists_are_cursor_paginated_and_invalid_cursor_is_recoverable(
    operator_member_client, organization, user
):
    _member, client = operator_member_client
    _create_evidence(organization=organization, user=user, marker="page-a")
    _create_evidence(organization=organization, user=user, marker="page-b")

    page = client.get("/api/v1/source-evidences?page_size=1")
    invalid_size = client.get("/api/v1/source-evidences?page_size=51")
    invalid_cursor = client.get("/api/v1/source-evidences?cursor=not-a-cursor")
    repeated_size = client.get("/api/v1/source-evidences?page_size=1&page_size=2")

    assert page.status_code == 200
    assert len(page.json()["results"]) == 1
    assert page.json()["next"]
    assert invalid_size.status_code == 400
    assert invalid_cursor.status_code == 400
    assert repeated_size.status_code == 400
    assert set(invalid_cursor.json()) >= {"code", "message", "recovery_action"}


def test_evidence_list_and_detail_expose_safe_provenance_and_internal_download_endpoint_only(
    operator_member_client, organization, user, asset, monkeypatch
):
    _member, client = operator_member_client
    evidence = _create_evidence(
        organization=organization, user=user, marker="download", asset=asset
    )
    monkeypatch.setattr(
        "apps.assets.storage.get_object_storage",
        lambda: pytest.fail("evidence reads must not presign storage URLs"),
    )

    listed = client.get("/api/v1/source-evidences")
    detail = client.get(f"/api/v1/source-evidences/{evidence.id}")

    assert listed.status_code == detail.status_code == 200
    row = listed.json()["results"][0]
    assert row == detail.json()
    assert row["screenshot_download_endpoint"] == (
        f"/api/v1/assets/{asset.id}/download-url"
    )
    assert "storage_key" not in row
    assert "credentials" not in row
    assert not any(
        value.startswith("http")
        for key, value in row.items()
        if key.endswith("endpoint") and value is not None
    )


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_source_evidence_detail_mutations_return_405(
    method, operator_member_client, organization, user
):
    _member, client = operator_member_client
    evidence = _create_evidence(organization=organization, user=user, marker=f"readonly-{method}")

    response = getattr(client, method)(
        f"/api/v1/source-evidences/{evidence.id}", {"original_text": "changed"}, format="json"
    )

    assert response.status_code == 405
    evidence.refresh_from_db()
    assert evidence.original_text == f"Need gear readonly-{method}"
