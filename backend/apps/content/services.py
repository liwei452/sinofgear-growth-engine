import uuid

from django.db import transaction

from apps.audit.services import record_review_transition
from apps.campaigns.models import ContentBrief
from apps.jobs.models import Job

from .models import MasterContent, PlatformContent, content_writes
from .payloads import validate_content_payload


class ContentStateError(ValueError):
    pass


def _master_provenance(content):
    return {
        "schema_version": 1,
        "root_content_id": str(content.lineage_id),
        "brief_id": str(content.brief_id),
        "brief_version": content.brief_version,
        "job_id": str(content.generation_job_id),
        "job_type": Job.Type.CONTENT_GENERATE,
        "ai_run_id": str(content.ai_run_id),
        "ai_run_job_attempt": content.ai_run.job_attempt,
        "prompt_version_id": str(content.ai_run.prompt_version_id),
    }


def _platform_provenance(content):
    return {
        "schema_version": 1,
        "root_platform_content_id": str(content.lineage_id),
        "master_content_id": str(content.master_content_id),
        "master_version": content.master_version,
        "master_lineage_id": str(content.master_content.lineage_id),
        "platform_id": str(content.platform_id),
        "platform_code": content.platform.code,
        "ai_provenance": content.master_content.provenance,
    }


def _previous_is_exact(content, fields):
    previous = content.previous_version
    if content.version == 1:
        return previous is None and content.lineage_id == content.id
    return (
        previous is not None
        and previous.version == content.version - 1
        and previous.lineage_id == content.lineage_id
        and previous.organization_id == content.organization_id
        and all(getattr(previous, field) == getattr(content, field) for field in fields)
        and previous.provenance == content.provenance
    )


def content_is_consistent(content):
    try:
        if isinstance(content, MasterContent):
            payload = validate_content_payload(content.payload)
            job = content.generation_job
            run = content.ai_run
            return (
                content.provenance == _master_provenance(content)
                and content.brief.organization_id == content.organization_id
                and content.brief_version == content.brief.version
                and job.organization_id == content.organization_id
                and job.type == Job.Type.CONTENT_GENERATE
                and job.status == Job.Status.SUCCEEDED
                and job.result_reference == {
                    "type": "master_content",
                    "id": str(content.lineage_id),
                    "version": 1,
                }
                and str(job.input_snapshot.get("brief_id")) == str(content.brief_id)
                and job.input_snapshot.get("brief_version") == content.brief_version
                and run.organization_id == content.organization_id
                and run.job_id == job.id
                and run.job_attempt == job.attempt
                and run.status == run.Status.SUCCEEDED
                and run.input_snapshot == job.input_snapshot
                and (content.version != 1 or payload == validate_content_payload(run.output_json))
                and _previous_is_exact(
                    content, ("brief_id", "brief_version", "generation_job_id", "ai_run_id")
                )
            )
        payload = validate_content_payload(
            content.payload, platform_code=content.platform.code
        )
        selected = getattr(content, "_selected_platform", None)
        if selected is None:
            selected = content.master_content.brief.platform_links.filter(
                platform_id=content.platform_id
            ).exists()
        return (
            bool(selected)
            and payload == content.payload
            and content.provenance == _platform_provenance(content)
            and content.master_content.organization_id == content.organization_id
            and content.master_version == content.master_content.version
            and content_is_consistent(content.master_content)
            and _previous_is_exact(
                content, ("master_content_id", "master_version", "platform_id")
            )
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


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
# Archiving is a historical tombstone operation, so it remains valid for a
# superseded row; all actions that can promote a usable head are head-only.
HEAD_ONLY_ACTIONS = frozenset({"SUBMIT", "APPROVE", "REJECT", "PUBLISH"})


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
    try:
        return validate_content_payload(payload)
    except ValueError as exc:
        raise ContentStateError(str(exc)) from exc


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
        or job.status != Job.Status.RUNNING
        or ai_run.status != ai_run.Status.SUCCEEDED
        or str(job.input_snapshot.get("brief_id")) != str(brief.id)
        or job.input_snapshot.get("brief_version") != brief.version
    ):
        raise ContentStateError("Generation provenance is inconsistent.")
    payload = _validated_payload(ai_run.output_json)
    content_id = uuid.uuid4()
    provenance_source = MasterContent(
        id=content_id, lineage_id=content_id, organization=brief.organization,
        brief=brief, brief_version=brief.version, generation_job=job, ai_run=ai_run,
    )
    with content_writes():
        return MasterContent.objects.create(
            id=content_id,
            organization=brief.organization,
            brief=brief,
            brief_version=brief.version,
            generation_job=job,
            ai_run=ai_run,
            payload=payload,
            lineage_id=content_id,
            provenance=_master_provenance(provenance_source),
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
    source = MasterContent.objects.select_for_update().select_related(
        "brief", "generation_job", "ai_run", "previous_version"
    ).get(pk=source.pk)
    if not content_is_consistent(source):
        raise ContentStateError("Content provenance is inconsistent.")
    if source.status == MasterContent.Status.ARCHIVED or MasterContent.objects.filter(
        previous_version=source
    ).exists():
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
    master = MasterContent.objects.select_for_update().select_related(
        "brief", "generation_job", "ai_run", "previous_version"
    ).get(pk=master.pk)
    if not content_is_consistent(master):
        raise ContentStateError("Master content provenance is inconsistent.")
    if master.status != MasterContent.Status.APPROVED:
        raise ContentStateError("Master content must be approved.")
    if MasterContent.objects.filter(previous_version=master).exists():
        raise ContentStateError("Platform content requires the approved current head.")
    if not master.brief.platform_links.filter(platform=platform).exists():
        raise ContentStateError("Platform was not selected by the source brief.")
    existing = PlatformContent.objects.filter(
        master_content=master, platform=platform, version=1
    ).first()
    if existing:
        if not content_is_consistent(existing):
            raise ContentStateError("Existing platform content provenance is inconsistent.")
        return existing
    payload = {
        "title": master.payload["title"],
        "body": master.payload["body"],
        "cta": master.payload["cta"],
        "concept_codes": list(master.payload["concept_codes"]),
        "platform_code": platform.code,
    }
    content_id = uuid.uuid4()
    provenance_source = PlatformContent(
        id=content_id, lineage_id=content_id, organization=master.organization,
        master_content=master, master_version=master.version, platform=platform,
    )
    payload = _validated_platform_payload(payload, platform.code)
    with content_writes():
        return PlatformContent.objects.create(
            id=content_id,
            organization=master.organization,
            master_content=master,
            master_version=master.version,
            platform=platform,
            payload=payload,
            lineage_id=content_id,
            provenance=_platform_provenance(provenance_source),
            status=PlatformContent.Status.IN_REVIEW,
            created_by=actor,
        )


def _validated_platform_payload(payload, platform_code):
    try:
        return validate_content_payload(payload, platform_code=platform_code)
    except ValueError as exc:
        raise ContentStateError(str(exc)) from exc


@transaction.atomic
def create_platform_revision(source, *, actor, payload):
    source = PlatformContent.objects.select_for_update().select_related(
        "platform", "previous_version", "master_content__brief",
        "master_content__generation_job", "master_content__ai_run",
        "master_content__previous_version",
    ).get(pk=source.pk)
    if not content_is_consistent(source):
        raise ContentStateError("Content provenance is inconsistent.")
    if source.status == PlatformContent.Status.ARCHIVED or PlatformContent.objects.filter(
        previous_version=source
    ).exists():
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
    if action in HEAD_ONLY_ACTIONS and model.objects.filter(
        previous_version=locked
    ).exists():
        raise ContentStateError("Only the current head can be reviewed.")
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
