import json
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.utils import timezone

from apps.assets.models import MaterialAsset
from apps.audit.models import AuditLog
from apps.identity.models import Membership, Role
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.leads.models import LeadCandidate, LeadReview, lead_history_writes
from apps.leads.services import LeadService
from apps.sources.models import (
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
    evidence_service_writes,
)
from apps.sources.services import EvidenceService, RetentionService


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


@pytest.mark.django_db
def test_cleanup_redacts_old_transient_evidence_and_preserves_fingerprint_history(
    organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

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
    assert result.deleted_text == 2
    assert result.anonymized_actors == 1
    assert result.protected == 0
    assert result.failures == 0
    assert result.no_op == 0


@pytest.mark.django_db
def test_cleanup_treats_exact_cutoff_as_not_older(organization, user):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="boundary",
        captured_at=cutoff,
    )

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    evidence.refresh_from_db()
    assert evidence.original_text
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.no_op == 1


@pytest.mark.django_db
def test_cleanup_keeps_confirmed_handoff_reviewed_and_active_analysis_evidence(
    organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    for row in (confirmed, handoff, reviewed, active):
        row.refresh_from_db()
        assert row.original_text
        assert row.availability == SourceEvidence.Availability.AVAILABLE
    assert result.protected == 4
    assert result.redacted == 0


@pytest.mark.django_db
def test_cleanup_keeps_evidence_referenced_by_confirm_review_history(
    organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    evidence.refresh_from_db()
    assert evidence.original_text
    assert result.protected == 1
    assert result.redacted == 0


@pytest.mark.django_db
def test_cleanup_does_not_anonymize_source_shared_with_protected_evidence(
    organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    transient.refresh_from_db()
    protected.refresh_from_db()
    transient.source_signal.source_content.refresh_from_db()
    assert transient.original_text == ""
    assert protected.original_text
    assert transient.source_signal.source_content.author_public_name
    assert transient.source_signal.source_content.original_text
    assert result.redacted == 1
    assert result.protected == 1
    assert result.anonymized_actors == 0


@pytest.mark.django_db
def test_cleanup_rechecks_active_analysis_after_evidence_lock(
    organization, user, monkeypatch
):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="analysis-race",
        captured_at=cutoff - timedelta(days=1),
    )
    reads = iter((set(), {str(evidence.id)}))
    monkeypatch.setattr(
        RetentionService,
        "_active_analysis_evidence_ids",
        lambda **_kwargs: next(reads),
    )

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    evidence.refresh_from_db()
    assert evidence.original_text
    assert result.protected == 1
    assert result.redacted == 0


@pytest.mark.django_db
def test_cleanup_ignores_unbound_malformed_active_snapshot_without_crashing(
    organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    evidence.refresh_from_db()
    assert evidence.original_text == ""
    assert result.redacted == 1


@pytest.mark.django_db
def test_cleanup_is_idempotent_and_does_not_duplicate_audit(organization, user):
    cutoff = timezone.now() - timedelta(days=30)
    evidence = _evidence(
        organization=organization,
        user=user,
        marker="twice",
        captured_at=cutoff - timedelta(days=1),
    )

    first = RetentionService.cleanup(organization=organization, cutoff=cutoff)
    second = RetentionService.cleanup(organization=organization, cutoff=cutoff)

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
    assert audit.actor is None
    serialized = json.dumps(audit.after_metadata, ensure_ascii=False)
    assert str(evidence.id) in serialized
    assert "Private public trace twice" not in serialized
    assert "Public Person twice" not in serialized


@pytest.mark.django_db
def test_cleanup_isolates_organizations(organization, other_organization, user):
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    own.refresh_from_db()
    foreign.refresh_from_db()
    assert own.original_text == ""
    assert foreign.original_text
    assert result.redacted == 1
    assert result.protected == 0
    assert result.failures == 0


@pytest.mark.django_db
def test_cleanup_leaves_inconsistent_row_atomic_and_counts_failure(
    organization, other_organization, user
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

    result = RetentionService.cleanup(organization=organization, cutoff=cutoff)

    evidence.refresh_from_db()
    assert evidence.original_text
    assert evidence.translated_text
    assert evidence.screenshot_asset_id == foreign_asset.id
    assert evidence.availability == SourceEvidence.Availability.AVAILABLE
    assert result.redacted == 0
    assert result.failures == 1


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
def test_cleanup_rejects_naive_cutoff(organization):
    with pytest.raises(ValueError, match="timezone-aware"):
        RetentionService.cleanup(
            organization=organization,
            cutoff=timezone.now().replace(tzinfo=None),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("cutoff", [None, "2026-07-11T00:00:00+00:00"])
def test_cleanup_rejects_non_datetime_cutoff(organization, cutoff):
    with pytest.raises(ValueError, match="timezone-aware datetime"):
        RetentionService.cleanup(organization=organization, cutoff=cutoff)
