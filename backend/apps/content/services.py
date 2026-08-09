from django.db import transaction

from apps.audit.services import record_review_transition
from apps.campaigns.models import ContentBrief
from apps.jobs.models import Job

from .models import MasterContent, PlatformContent, content_writes


class ContentStateError(ValueError):
    pass


def content_is_consistent(content):
    if isinstance(content, MasterContent):
        previous = content.previous_version
        return (
            content.brief.organization_id == content.organization_id
            and content.generation_job.organization_id == content.organization_id
            and content.ai_run.organization_id == content.organization_id
            and content.ai_run.job_id == content.generation_job_id
            and content.brief_version == content.brief.version
            and (
                previous is None
                or (
                    previous.organization_id == content.organization_id
                    and previous.lineage_id == content.lineage_id
                    and content.version == previous.version + 1
                    and previous.brief_id == content.brief_id
                    and previous.generation_job_id == content.generation_job_id
                    and previous.ai_run_id == content.ai_run_id
                )
            )
        )
    previous = content.previous_version
    return (
        content.master_content.organization_id == content.organization_id
        and content.master_version == content.master_content.version
        and content.master_content.brief.platform_links.filter(platform=content.platform).exists()
        and (
            previous is None
            or (
                previous.organization_id == content.organization_id
                and previous.lineage_id == content.lineage_id
                and content.version == previous.version + 1
                and previous.master_content_id == content.master_content_id
                and previous.platform_id == content.platform_id
            )
        )
    )


MASTER_TRANSITIONS = {
    ("DRAFT", "SUBMIT"): "IN_REVIEW",
    ("IN_REVIEW", "APPROVE"): "APPROVED",
    ("IN_REVIEW", "REJECT"): "REJECTED",
    ("DRAFT", "ARCHIVE"): "ARCHIVED",
    ("IN_REVIEW", "ARCHIVE"): "ARCHIVED",
    ("APPROVED", "ARCHIVE"): "ARCHIVED",
    ("REJECTED", "ARCHIVE"): "ARCHIVED",
}
PLATFORM_TRANSITIONS = {
    **MASTER_TRANSITIONS,
    ("APPROVED", "PUBLISH"): "PUBLISHED",
    ("PUBLISHED", "ARCHIVE"): "ARCHIVED",
}


def _transition(mapping, source, action, comment):
    if action == "REJECT" and not comment.strip():
        raise ContentStateError("Reject comment must not be empty.")
    try:
        return mapping[(source, action)]
    except KeyError as exc:
        raise ContentStateError(f"Cannot {action.lower()} content in status {source}.") from exc


def master_transition(source, action, *, comment=""):
    return _transition(MASTER_TRANSITIONS, source, action, comment)


def platform_transition(source, action, *, comment=""):
    return _transition(PLATFORM_TRANSITIONS, source, action, comment)


def _validated_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {
        "title", "body", "cta", "concept_codes",
    }:
        raise ContentStateError("Content payload does not match the master schema.")
    cleaned = {
        key: value.strip() if isinstance(value, str) else ""
        for key, value in payload.items() if key != "concept_codes"
    }
    codes = payload["concept_codes"]
    if (
        not all(cleaned.values())
        or any(len(value) > 50_000 for value in cleaned.values())
        or not isinstance(codes, list)
        or any(not isinstance(code, str) or not code.strip() for code in codes)
    ):
        raise ContentStateError("Content payload fields must be nonempty and bounded.")
    cleaned["concept_codes"] = list(codes)
    return cleaned


@transaction.atomic
def create_generated_master(*, brief, job, ai_run, actor=None):
    existing = MasterContent.objects.filter(generation_job=job, ai_run=ai_run).first()
    if existing:
        if not content_is_consistent(existing):
            raise ContentStateError("Existing content provenance is inconsistent.")
        return existing
    if (
        brief.status != brief.Status.READY
        or job.organization_id != brief.organization_id
        or ai_run.organization_id != brief.organization_id
        or ai_run.job_id != job.id
        or job.status not in {Job.Status.RUNNING, Job.Status.SUCCEEDED}
        or ai_run.status != ai_run.Status.SUCCEEDED
        or str(job.input_snapshot.get("brief_id")) != str(brief.id)
        or job.input_snapshot.get("brief_version") != brief.version
    ):
        raise ContentStateError("Generation provenance is inconsistent.")
    payload = _validated_payload(ai_run.output_json)
    with content_writes():
        return MasterContent.objects.create(
            organization=brief.organization,
            brief=brief,
            brief_version=brief.version,
            generation_job=job,
            ai_run=ai_run,
            payload=payload,
            provenance={
                "brief_id": str(brief.id),
                "brief_version": brief.version,
                "job_id": str(job.id),
                "ai_run_id": str(ai_run.id),
                "prompt_version_id": str(ai_run.prompt_version_id),
            },
            status=MasterContent.Status.IN_REVIEW,
            created_by=actor,
        )


def finalize_master_result(run, output):
    del output
    brief = ContentBrief.objects.get(
        pk=run.input_snapshot.get("brief_id"), organization=run.organization
    )
    master = create_generated_master(
        brief=brief,
        job=run.job,
        ai_run=run,
        actor=run.job.created_by,
    )
    return {"type": "master_content", "id": str(master.id), "version": master.version}


@transaction.atomic
def create_master_revision(source, *, actor, payload):
    source = MasterContent.objects.select_for_update().get(pk=source.pk)
    if not content_is_consistent(source):
        raise ContentStateError("Content provenance is inconsistent.")
    if source.status == MasterContent.Status.ARCHIVED or hasattr(source, "next_version"):
        raise ContentStateError("Content lineage cannot branch or revise archived content.")
    cleaned = _validated_payload(payload)
    if cleaned == source.payload:
        raise ContentStateError("Content revision must change the payload.")
    with content_writes():
        return MasterContent.objects.create(
            organization=source.organization,
            brief=source.brief,
            brief_version=source.brief_version,
            generation_job=source.generation_job,
            ai_run=source.ai_run,
            lineage_id=source.lineage_id,
            previous_version=source,
            version=source.version + 1,
            payload=cleaned,
            provenance=source.provenance,
            status=MasterContent.Status.DRAFT,
            created_by=actor,
        )


@transaction.atomic
def create_platform_content(master, *, platform, actor=None):
    master = MasterContent.objects.select_for_update().get(pk=master.pk)
    if not content_is_consistent(master):
        raise ContentStateError("Master content provenance is inconsistent.")
    existing = PlatformContent.objects.filter(
        master_content=master, platform=platform, version=1
    ).first()
    if existing:
        return existing
    if master.status != MasterContent.Status.APPROVED:
        raise ContentStateError("Master content must be approved.")
    if not master.brief.platform_links.filter(platform=platform).exists():
        raise ContentStateError("Platform was not selected by the source brief.")
    payload = {
        "title": master.payload["title"],
        "body": master.payload["body"],
        "cta": master.payload["cta"],
        "concept_codes": list(master.payload["concept_codes"]),
        "platform_code": platform.code,
    }
    with content_writes():
        return PlatformContent.objects.create(
            organization=master.organization,
            master_content=master,
            master_version=master.version,
            platform=platform,
            payload=payload,
            provenance={
                "master_content_id": str(master.id),
                "master_version": master.version,
                "platform_id": str(platform.id),
            },
            status=PlatformContent.Status.IN_REVIEW,
            created_by=actor,
        )


def _validated_platform_payload(payload, platform_code):
    if not isinstance(payload, dict) or set(payload) != {
        "title", "body", "cta", "concept_codes", "platform_code",
    }:
        raise ContentStateError("Content payload does not match the platform schema.")
    if payload.get("platform_code") != platform_code:
        raise ContentStateError("Platform identity cannot change in a revision.")
    master_shape = {key: payload[key] for key in ("title", "body", "cta", "concept_codes")}
    return {**_validated_payload(master_shape), "platform_code": platform_code}


@transaction.atomic
def create_platform_revision(source, *, actor, payload):
    source = PlatformContent.objects.select_for_update().get(pk=source.pk)
    if not content_is_consistent(source):
        raise ContentStateError("Content provenance is inconsistent.")
    if source.status == PlatformContent.Status.ARCHIVED or hasattr(source, "next_version"):
        raise ContentStateError("Content lineage cannot branch or revise archived content.")
    cleaned = _validated_platform_payload(payload, source.platform.code)
    if cleaned == source.payload:
        raise ContentStateError("Content revision must change the payload.")
    with content_writes():
        return PlatformContent.objects.create(
            organization=source.organization,
            master_content=source.master_content,
            master_version=source.master_version,
            platform=source.platform,
            lineage_id=source.lineage_id,
            previous_version=source,
            version=source.version + 1,
            payload=cleaned,
            provenance=source.provenance,
            status=PlatformContent.Status.DRAFT,
            created_by=actor,
        )


@transaction.atomic
def transition_content(content, *, action, actor, comment=""):
    model = type(content)
    locked = model.objects.select_for_update().get(pk=content.pk)
    if not content_is_consistent(locked):
        raise ContentStateError("Content provenance is inconsistent.")
    transition = master_transition if model is MasterContent else platform_transition
    target = transition(locked.status, action, comment=comment)
    before = {"status": locked.status}
    locked.status = target
    with content_writes():
        locked.save(update_fields=["status", "updated_at"])
    record_review_transition(
        organization=locked.organization,
        object_type=f"content.{model.__name__}",
        object_id=locked.id,
        action=action,
        status=target,
        object_version=locked.version,
        actor=actor,
        comment=comment.strip(),
        before_metadata=before,
        after_metadata={"status": target},
    )
    return locked


def approve_content(content, *, actor, comment=""):
    return transition_content(content, action="APPROVE", actor=actor, comment=comment)


def reject_content(content, *, actor, comment):
    return transition_content(content, action="REJECT", actor=actor, comment=comment)
