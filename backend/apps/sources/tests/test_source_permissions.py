import pytest

from apps.assets.models import MaterialAsset
from apps.sources.models import IngestionBatch, MonitoringTarget, SourceEvidence
from apps.sources.services import EvidenceService


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("endpoint", ["monitoring-targets", "ingestion-batches"])
def test_read_only_member_can_list_but_cannot_create(endpoint, read_only_member_client):
    _member, client = read_only_member_client

    assert client.get(f"/api/v1/{endpoint}").status_code == 200
    response = client.post(f"/api/v1/{endpoint}", {}, format="json")
    assert response.status_code == 403
    assert set(response.json()) >= {"code", "message", "recovery_action"}


def test_operator_can_create_source_resources(operator_member_client):
    _member, client = operator_member_client

    response = client.post(
        "/api/v1/monitoring-targets",
        {
            "target_type": "KEYWORD",
            "collection_mode": "PASTE",
            "platform": "MANUAL",
            "external_reference": "replacement gear",
            "label": "Replacement gear",
        },
        format="json",
    )

    assert response.status_code == 201


def test_cross_organization_monitoring_target_is_indistinguishable_from_missing(
    operator_member_client, other_organization, user
):
    _member, client = operator_member_client
    other_target = MonitoringTarget.objects.create(
        organization=other_organization,
        target_type=MonitoringTarget.TargetType.POST,
        collection_mode=MonitoringTarget.CollectionMode.MANUAL_URL,
        platform="OTHER",
        normalized_url="https://other.test/target",
        label="Private other target",
        created_by=user,
    )
    request = {
        "source_type": "PASTE",
        "monitoring_target_id": str(other_target.id),
        "idempotency_key": "foreign-target",
        "payload": {"text": "https://e.test/one\tNeed gear"},
    }

    response = client.post("/api/v1/ingestion-batches", request, format="json")

    assert response.status_code == 400
    assert "Private other target" not in str(response.json())
    assert IngestionBatch.objects.count() == 0


@pytest.mark.parametrize("unavailable_reason", ["cross_organization", "archived"])
def test_import_asset_must_be_active_and_owned(
    unavailable_reason, operator_member_client, asset, other_asset
):
    _member, client = operator_member_client
    selected_asset = other_asset
    if unavailable_reason == "archived":
        asset.status = MaterialAsset.Status.ARCHIVED
        asset.save(update_fields=["status", "updated_at"])
        selected_asset = asset
    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "JSON",
            "import_asset_id": str(selected_asset.id),
            "idempotency_key": f"unavailable-asset-{unavailable_reason}",
            "payload": {
                "rows": [{"source_url": "https://e.test/a", "original_text": "Need gear"}]
            },
        },
        format="json",
    )

    assert response.status_code == 400
    assert "other" not in str(response.json()).lower()
    assert IngestionBatch.objects.count() == 0


def test_disabled_monitoring_target_is_not_accepted(operator_member_client, target):
    _member, client = operator_member_client
    target.enabled = False
    target.save(update_fields=["enabled", "updated_at"])

    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "URL",
            "monitoring_target_id": str(target.id),
            "idempotency_key": "disabled-target",
            "payload": {"source_url": "https://e.test/a", "original_text": "Need gear"},
        },
        format="json",
    )

    assert response.status_code == 400
    assert IngestionBatch.objects.count() == 0


def test_nested_import_asset_id_cannot_bypass_top_level_scope_validation(
    operator_member_client, other_asset
):
    _member, client = operator_member_client

    response = client.post(
        "/api/v1/ingestion-batches",
        {
            "source_type": "JSON",
            "idempotency_key": "nested-foreign-asset",
            "payload": {
                "import_asset_id": str(other_asset.id),
                "rows": [
                    {"source_url": "https://e.test/nested", "original_text": "Need gear"}
                ],
            },
        },
        format="json",
    )

    assert response.status_code == 400
    assert str(other_asset.id) not in str(response.json())
    assert IngestionBatch.objects.count() == 0


def test_all_read_collections_hide_other_organization_rows(
    operator_member_client, other_operator_member_client
):
    own_member, own_client = operator_member_client
    _other_member, other_client = other_operator_member_client
    created = other_client.post(
        "/api/v1/monitoring-targets",
        {
            "target_type": "KEYWORD",
            "collection_mode": "PASTE",
            "platform": "OTHER",
            "external_reference": "private-other",
            "label": "Other target",
        },
        format="json",
    )
    assert created.status_code == 201

    for endpoint in (
        "monitoring-targets",
        "ingestion-batches",
        "source-contents",
        "source-signals",
        "source-evidences",
    ):
        response = own_client.get(f"/api/v1/{endpoint}")
        assert response.status_code == 200
        assert response.json()["results"] == []
    assert own_member.memberships.get().organization != (
        other_operator_member_client[0].memberships.get().organization
    )


def test_read_only_member_can_retrieve_evidence_but_mutation_is_405(
    read_only_member_client, signal
):
    member, client = read_only_member_client
    evidence = EvidenceService.create(
        organization=signal.organization,
        signal=signal,
        original_text="Public evidence",
        source_url="https://e.test/read-only",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.URL,
        public_published_at=None,
        created_by=member,
    )

    retrieved = client.get(f"/api/v1/source-evidences/{evidence.id}")
    mutation = client.patch(
        f"/api/v1/source-evidences/{evidence.id}",
        {"original_text": "changed"},
        format="json",
    )

    assert retrieved.status_code == 200
    assert mutation.status_code == 405


def test_evidence_detail_hides_cross_organization_existence(
    other_operator_member_client, signal
):
    _other_member, other_client = other_operator_member_client
    evidence = EvidenceService.create(
        organization=signal.organization,
        signal=signal,
        original_text="Private tenant evidence",
        source_url="https://e.test/private-tenant",
        platform="MANUAL",
        collection_method=SourceEvidence.CollectionMethod.URL,
        public_published_at=None,
        created_by=signal.created_by,
    )

    response = other_client.get(f"/api/v1/source-evidences/{evidence.id}")

    assert response.status_code == 404
    assert "Private tenant evidence" not in str(response.json())
