import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import ApprovalRecord, AuditLog
from apps.content.models import MasterContent
from apps.content.services import (
    ContentStateError,
    approve_content,
    create_generated_master,
    create_master_revision,
    reject_content,
    create_platform_content,
    create_platform_revision,
    transition_content,
)
from apps.platforms.models import Platform


def test_generated_master_is_in_review_and_duplicate_is_idempotent(content_provenance):
    _, actor, brief, job, run = content_provenance

    first = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    duplicate = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    assert first.status == MasterContent.Status.IN_REVIEW
    assert first.version == 1
    assert first.payload == run.output_json
    assert duplicate.pk == first.pk


def test_approve_records_shared_approval_and_audit(content_provenance):
    organization, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    approved = approve_content(content, actor=actor, comment="checked")

    assert approved.status == MasterContent.Status.APPROVED
    approval = ApprovalRecord.objects.get(object_id=approved.id, action="APPROVE")
    audit = AuditLog.objects.get(object_id=approved.id, action="APPROVE")
    assert approval.organization == organization
    assert approval.actor == actor
    assert approval.object_version == approved.version
    assert audit.after_metadata["status"] == "APPROVED"


def test_reject_requires_comment_and_rolls_back(content_provenance):
    _, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    with pytest.raises(ContentStateError):
        reject_content(content, actor=actor, comment=" ")

    content.refresh_from_db()
    assert content.status == MasterContent.Status.IN_REVIEW
    assert ApprovalRecord.objects.filter(object_id=content.id).count() == 0


def test_human_edit_creates_linear_draft_revision_without_overwriting_source(
    content_provenance,
):
    _, actor, brief, job, run = content_provenance
    source = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    revision = create_master_revision(
        source, actor=actor,
        payload={
            "title": "Human edit", "body": "Body", "cta": "Quote",
            "concept_codes": [],
        },
    )

    source.refresh_from_db()
    assert source.payload["title"] == "Generated"
    assert revision.status == MasterContent.Status.DRAFT
    assert revision.previous_version == source
    assert revision.lineage_id == source.lineage_id
    assert revision.version == 2
    with pytest.raises(ContentStateError):
        create_master_revision(source, actor=actor, payload=revision.payload)


def test_content_history_rejects_direct_bulk_and_delete(content_provenance):
    _, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    content.payload = {"title": "forged"}

    with pytest.raises(ValidationError):
        content.save()
    with pytest.raises(ValidationError):
        MasterContent._base_manager.filter(pk=content.pk).update(status="APPROVED")
    with pytest.raises(ValidationError):
        content.delete()


def test_platform_generation_requires_approved_master_and_selected_platform(
    content_provenance,
):
    organization, actor, brief, job, run = content_provenance
    selected = brief.platform_links.get().platform
    other = Platform.objects.create(code="OTHER", name="Other")
    master = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    with pytest.raises(ContentStateError):
        create_platform_content(master, platform=selected, actor=actor)
    approved = approve_content(master, actor=actor)
    with pytest.raises(ContentStateError):
        create_platform_content(approved, platform=other, actor=actor)

    platform_content = create_platform_content(
        approved, platform=selected, actor=actor
    )
    duplicate = create_platform_content(approved, platform=selected, actor=actor)
    assert platform_content.status == "IN_REVIEW"
    assert platform_content.master_version == approved.version
    assert platform_content.payload["platform_code"] == "SELECTED"
    assert duplicate.pk == platform_content.pk


def test_platform_approval_auto_prepares_channel_package(content_provenance, monkeypatch):
    _, actor, brief, job, run = content_provenance
    selected = brief.platform_links.get().platform
    master = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    approved = approve_content(master, actor=actor)
    platform_content = create_platform_content(approved, platform=selected, actor=actor)

    calls = []
    monkeypatch.setattr(
        "apps.growth.services.prepare_channel_package_from_platform_content",
        lambda *, content: calls.append(content) or (None, True),
    )

    approve_content(platform_content, actor=actor)

    assert [content.pk for content in calls] == [platform_content.pk]


def test_approval_history_rejects_direct_base_bulk_and_delete(content_provenance):
    _, actor, brief, job, run = content_provenance
    content = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    approve_content(content, actor=actor)
    approval = ApprovalRecord.objects.get(object_id=content.id)
    approval.comment = "forged"

    with pytest.raises(ValidationError):
        approval.save()
    with pytest.raises(ValidationError):
        ApprovalRecord._base_manager.filter(pk=approval.pk).update(status="REJECTED")
    with pytest.raises(ValidationError):
        ApprovalRecord.objects.bulk_update([approval], ["comment"])
    with pytest.raises(ValidationError):
        approval.delete()


def test_platform_human_revision_is_linear_draft(content_provenance):
    _, actor, brief, job, run = content_provenance
    platform = brief.platform_links.get().platform
    master = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    master = approve_content(master, actor=actor)
    source = create_platform_content(master, platform=platform, actor=actor)

    revision = create_platform_revision(
        source, actor=actor, payload={**source.payload, "title": "Platform edit"}
    )

    assert revision.status == "DRAFT"
    assert revision.previous_version == source
    assert revision.lineage_id == source.lineage_id
    assert revision.version == 2
    with pytest.raises(ContentStateError):
        create_platform_revision(source, actor=actor, payload=revision.payload)


@pytest.mark.parametrize("action", ["APPROVE", "REJECT"])
def test_superseded_master_cannot_be_reviewed(content_provenance, action):
    _, actor, brief, job, run = content_provenance
    source = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)
    create_master_revision(
        source, actor=actor, payload={**source.payload, "title": "new head"}
    )

    with pytest.raises(ContentStateError, match="current head"):
        transition_content(source, action=action, actor=actor, comment="reason")


@pytest.mark.parametrize("action", ["APPROVE", "REJECT"])
def test_superseded_platform_cannot_be_reviewed(content_provenance, action):
    _, actor, brief, job, run = content_provenance
    platform = brief.platform_links.get().platform
    master = approve_content(
        create_generated_master(brief=brief, job=job, ai_run=run, actor=actor), actor=actor
    )
    source = create_platform_content(master, platform=platform, actor=actor)
    create_platform_revision(
        source, actor=actor, payload={**source.payload, "title": "new head"}
    )

    with pytest.raises(ContentStateError, match="current head"):
        transition_content(source, action=action, actor=actor, comment="reason")


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "T", "body": "B", "cta": "C", "concept_codes": ["X"] * 101},
        {"title": "T", "body": "B", "cta": "C", "concept_codes": ["X", " X "]},
        {"title": "T", "body": "B", "cta": "C", "concept_codes": ["X" * 257]},
        {
            "title": "T" * 500,
            "body": "B" * 50_000,
            "cta": "C" * 2_000,
            "concept_codes": [f"{index:03d}" + "X" * 253 for index in range(100)],
        },
    ],
)
def test_revision_payload_has_shared_bounded_exact_schema(content_provenance, payload):
    _, actor, brief, job, run = content_provenance
    source = create_generated_master(brief=brief, job=job, ai_run=run, actor=actor)

    with pytest.raises(ContentStateError):
        create_master_revision(source, actor=actor, payload=payload)
