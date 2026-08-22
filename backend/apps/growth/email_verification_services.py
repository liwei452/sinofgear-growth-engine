from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.common.tenancy import tenant_atomic
from apps.common.tenant_tasks import dispatch_task_on_commit

from .email_verification import (
    LocalVerificationResult,
    VERIFIER_VERSION,
    VerificationHistory,
    VerificationStatus,
    get_local_verifier,
)
from .models import (
    Contact,
    DiscoveryCandidate,
    EmailVerificationEvidence,
    EmailVerificationRun,
    OutreachMessage,
)


class EmailVerificationExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedEmailVerification:
    run_id: uuid.UUID
    claim_token: uuid.UUID
    email: str
    contact_name: str
    corporate_domain: str
    high_value: bool
    history: VerificationHistory


class LocalVerifierLike(Protocol):
    def verify(self, email: object, **kwargs) -> LocalVerificationResult: ...


def _native_uuid(value, field_name: str) -> uuid.UUID:
    if type(value) is not uuid.UUID:
        raise TypeError(f"{field_name} must be a native UUID instance.")
    return value


def normalize_email(value: object) -> str:
    return value.strip().lower() if type(value) is str else ""


def request_email_verification(
    *,
    organization_id: uuid.UUID,
    email: object,
    idempotency_key: str | None,
    contact_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    contact_name: str = "",
    corporate_domain: str = "",
    high_value: bool = False,
    dispatch: bool = True,
) -> tuple[EmailVerificationRun, bool]:
    organization_id = _native_uuid(organization_id, "organization_id")
    if idempotency_key is not None and (
        type(idempotency_key) is not str or not idempotency_key.strip()
    ):
        raise ValidationError("idempotency_key must be a non-empty string when provided.")
    if type(high_value) is not bool:
        raise ValidationError("high_value must be a boolean.")
    normalized = normalize_email(email)
    domain = normalized.rsplit("@", 1)[1] if "@" in normalized else ""
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
    with tenant_atomic(organization_id):
        contact = None
        candidate = None
        if contact_id is not None:
            contact = Contact.objects.filter(
                organization_id=organization_id,
                id=_native_uuid(contact_id, "contact_id"),
            ).first()
            if contact is None:
                raise ValidationError("Verification parent is unavailable.")
        if candidate_id is not None:
            candidate = DiscoveryCandidate.objects.filter(
                organization_id=organization_id,
                id=_native_uuid(candidate_id, "candidate_id"),
            ).first()
            if candidate is None:
                raise ValidationError("Verification parent is unavailable.")
        effective_contact_name = (
            contact_name or (contact.full_name if contact else "")
        ).strip()
        effective_corporate_domain = corporate_domain.strip().lower().rstrip(".")
        history = _verification_history(organization_id, normalized)
        history_snapshot = {
            "replied": history.replied,
            "bounced": history.bounced,
            "sent_count": history.sent_count,
            "source_fingerprint": history.source_fingerprint,
        }
        request_context = {
            "email": normalized,
            "contact_id": str(contact.id) if contact else None,
            "candidate_id": str(candidate.id) if candidate else None,
            "contact_name": effective_contact_name,
            "corporate_domain": effective_corporate_domain,
            "high_value": high_value,
            "history": history_snapshot,
            "verifier_version": VERIFIER_VERSION,
        }
        request_fingerprint = hashlib.sha256(
            json.dumps(request_context, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        safe_snapshot = {
            "contact_name": effective_contact_name,
            "corporate_domain": effective_corporate_domain,
            "high_value": high_value,
            "history": history_snapshot,
            "request_fingerprint": request_fingerprint,
        }
        effective_idempotency_key = (
            idempotency_key.strip()
            if idempotency_key is not None
            else f"email-verify:v2:{request_fingerprint}"
        )
        run, created = EmailVerificationRun.objects.get_or_create(
            organization_id=organization_id,
            idempotency_key=effective_idempotency_key,
            defaults={
                "contact": contact,
                "candidate": candidate,
                "normalized_email": normalized,
                "email_fingerprint": fingerprint,
                "domain": domain,
                "request_snapshot": safe_snapshot,
                "verifier_version": VERIFIER_VERSION,
            },
        )
        if not created and (
            run.normalized_email != normalized
            or run.contact_id != (contact.id if contact else None)
            or run.candidate_id != (candidate.id if candidate else None)
            or run.request_snapshot != safe_snapshot
            or run.verifier_version != VERIFIER_VERSION
        ):
            raise ValidationError("Idempotency key is already bound to another request.")
        if created and dispatch:
            from .tasks import run_email_verification

            dispatch_task_on_commit(
                run_email_verification,
                str(organization_id),
                str(run.id),
            )
        return run, created


def _verification_history(organization_id: uuid.UUID, email: str) -> VerificationHistory:
    messages = OutreachMessage.objects.filter(
        organization_id=organization_id,
        payload__email=email,
    ).order_by("-created_at", "-id")
    latest_decisive = messages.filter(
        status__in=[
            OutreachMessage.Status.REPLIED,
            OutreachMessage.Status.BOUNCED,
        ]
    ).first()
    sent_messages = messages.filter(status=OutreachMessage.Status.SENT)
    sent_count = sent_messages.count()
    latest_sent = sent_messages.first()
    fingerprint_material = {
        "latest_decisive_id": str(latest_decisive.id) if latest_decisive else None,
        "latest_decisive_status": latest_decisive.status if latest_decisive else None,
        "latest_decisive_updated_at": (
            latest_decisive.updated_at.isoformat() if latest_decisive else None
        ),
        "latest_sent_id": str(latest_sent.id) if latest_sent else None,
        "latest_sent_updated_at": latest_sent.updated_at.isoformat() if latest_sent else None,
        "sent_count": sent_count,
    }
    source_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return VerificationHistory(
        replied=bool(
            latest_decisive and latest_decisive.status == OutreachMessage.Status.REPLIED
        ),
        bounced=bool(
            latest_decisive and latest_decisive.status == OutreachMessage.Status.BOUNCED
        ),
        sent_count=sent_count,
        source_fingerprint=source_fingerprint,
    )


def _prepare_email_verification(
    *, organization_id: uuid.UUID, run_id: uuid.UUID
) -> tuple[EmailVerificationRun, PreparedEmailVerification | None]:
    with tenant_atomic(organization_id):
        run = EmailVerificationRun.objects.select_for_update().filter(
            organization_id=organization_id,
            id=run_id,
        ).first()
        if run is None:
            raise ValidationError("Verification run is unavailable.")
        if run.state == EmailVerificationRun.State.RUNNING:
            claim_timeout = _claim_timeout_seconds()
            claim_fresh_after = timezone.now() - timedelta(seconds=claim_timeout)
            if run.started_at and run.started_at >= claim_fresh_after:
                return run, None
        if run.state in {
            EmailVerificationRun.State.PAUSED,
            EmailVerificationRun.State.SUCCEEDED,
        }:
            return run, None
        claim_token = uuid.uuid4()
        run.state = EmailVerificationRun.State.RUNNING
        run.claim_token = claim_token
        run.attempt_count += 1
        run.started_at = timezone.now()
        run.completed_at = None
        run.safe_error_code = ""
        run.save(
            update_fields=[
                "state",
                "claim_token",
                "attempt_count",
                "started_at",
                "completed_at",
                "safe_error_code",
                "updated_at",
            ]
        )
        snapshot = run.request_snapshot or {}
        history_snapshot = snapshot.get("history")
        if isinstance(history_snapshot, dict):
            history = VerificationHistory(
                replied=history_snapshot.get("replied") is True,
                bounced=history_snapshot.get("bounced") is True,
                sent_count=(
                    history_snapshot.get("sent_count")
                    if type(history_snapshot.get("sent_count")) is int
                    and history_snapshot.get("sent_count") >= 0
                    else 0
                ),
                source_fingerprint=(
                    history_snapshot.get("source_fingerprint")
                    if type(history_snapshot.get("source_fingerprint")) is str
                    else ""
                ),
            )
        else:
            history = _verification_history(organization_id, run.normalized_email)
        prepared = PreparedEmailVerification(
            run_id=run.id,
            claim_token=claim_token,
            email=run.normalized_email,
            contact_name=str(snapshot.get("contact_name") or ""),
            corporate_domain=str(snapshot.get("corporate_domain") or ""),
            high_value=snapshot.get("high_value") is True,
            history=history,
        )
        return run, prepared


def _provider_is_needed(result: LocalVerificationResult, *, high_value: bool) -> bool:
    return bool(
        high_value
        or result.catch_all
        or result.status in {VerificationStatus.RISKY, VerificationStatus.UNKNOWN}
    )


def _claim_timeout_seconds() -> int:
    value = getattr(settings, "EMAIL_VERIFICATION_CLAIM_TIMEOUT_SECONDS", 120)
    if type(value) is not int or not 30 <= value <= 3600:
        raise EmailVerificationExecutionError("claim_timeout_invalid")
    return value


def _finalize_email_verification(
    *,
    organization_id: uuid.UUID,
    prepared: PreparedEmailVerification,
    local_result: LocalVerificationResult,
) -> EmailVerificationRun:
    with tenant_atomic(organization_id):
        run = EmailVerificationRun.objects.select_for_update().get(
            organization_id=organization_id,
            id=prepared.run_id,
        )
        if (
            run.state != EmailVerificationRun.State.RUNNING
            or run.claim_token != prepared.claim_token
        ):
            return run
        starting_sequence = run.evidence_items.count()
        rows = []
        for offset, item in enumerate(local_result.evidence, start=1):
            safe_details = {
                key: value
                for key, value in item.details.items()
                if key in {"mx_count", "response_code"}
                and (value is None or type(value) is int)
            }
            rows.append(
                EmailVerificationEvidence(
                    organization_id=organization_id,
                    run=run,
                    sequence=starting_sequence + offset,
                    check_type=item.check_type,
                    source=item.source,
                    source_version=item.source_version,
                    outcome=item.outcome,
                    reason_code=item.reason_code,
                    evidence=safe_details,
                    observed_at=item.observed_at,
                )
            )
        EmailVerificationEvidence.objects.bulk_create(rows)
        run.state = EmailVerificationRun.State.SUCCEEDED
        run.result_status = local_result.status.value
        run.deliverability_score = local_result.deliverability_score
        run.contact_quality_score = local_result.contact_quality_score
        run.reason_codes = list(local_result.reason_codes)
        run.requires_provider_review = _provider_is_needed(
            local_result, high_value=prepared.high_value
        )
        run.result_source = "LOCAL"
        run.completed_at = timezone.now()
        run.claim_token = None
        run.full_clean()
        run.save(
            update_fields=[
                "state",
                "result_status",
                "deliverability_score",
                "contact_quality_score",
                "reason_codes",
                "requires_provider_review",
                "result_source",
                "completed_at",
                "claim_token",
                "updated_at",
            ]
        )
        return run


def _finalize_failure(
    *, organization_id: uuid.UUID, prepared: PreparedEmailVerification
) -> None:
    with tenant_atomic(organization_id):
        run = EmailVerificationRun.objects.select_for_update().filter(
            organization_id=organization_id,
            id=prepared.run_id,
            state=EmailVerificationRun.State.RUNNING,
            claim_token=prepared.claim_token,
        ).first()
        if run is None:
            return
        run.state = EmailVerificationRun.State.FAILED
        run.safe_error_code = "VERIFICATION_NETWORK_FAILED"
        run.claim_token = None
        run.completed_at = timezone.now()
        run.save(
            update_fields=[
                "state",
                "safe_error_code",
                "claim_token",
                "completed_at",
                "updated_at",
            ]
        )


def execute_email_verification(
    *,
    organization_id: uuid.UUID,
    run_id: uuid.UUID,
    local_verifier: LocalVerifierLike | None = None,
) -> EmailVerificationRun:
    organization_id = _native_uuid(organization_id, "organization_id")
    run_id = _native_uuid(run_id, "run_id")
    run, prepared = _prepare_email_verification(
        organization_id=organization_id,
        run_id=run_id,
    )
    if prepared is None:
        return run
    if connection.in_atomic_block:
        raise EmailVerificationExecutionError("Network phase requires a committed transaction.")
    verifier = local_verifier or get_local_verifier()
    try:
        local_result = verifier.verify(
            prepared.email,
            contact_name=prepared.contact_name,
            corporate_domain=prepared.corporate_domain,
            history=prepared.history,
        )
    except Exception:
        _finalize_failure(organization_id=organization_id, prepared=prepared)
        raise EmailVerificationExecutionError("verification_network_failed") from None
    return _finalize_email_verification(
        organization_id=organization_id,
        prepared=prepared,
        local_result=local_result,
    )


def verify_email_for_tenant(
    *,
    organization_id: uuid.UUID,
    email: object,
    candidate_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    contact_name: str = "",
    corporate_domain: str = "",
    high_value: bool = False,
    force_refresh: bool = False,
    local_verifier: LocalVerifierLike | None = None,
) -> dict:
    if type(force_refresh) is not bool:
        raise ValidationError("force_refresh must be a boolean.")
    normalized = normalize_email(email)
    idempotency_key = None
    if force_refresh:
        idempotency_key = f"email-verify:refresh:{uuid.uuid4()}"
    run, _ = request_email_verification(
        organization_id=organization_id,
        email=normalized,
        idempotency_key=idempotency_key,
        candidate_id=candidate_id,
        contact_id=contact_id,
        contact_name=contact_name,
        corporate_domain=corporate_domain,
        high_value=high_value,
        dispatch=False,
    )
    run = execute_email_verification(
        organization_id=organization_id,
        run_id=run.id,
        local_verifier=local_verifier,
    )
    return {
        "verification_id": str(run.id),
        "email": run.normalized_email,
        "state": run.state,
        "status": run.result_status,
        "deliverability_score": run.deliverability_score,
        "contact_quality_score": run.contact_quality_score,
        "reason_codes": list(run.reason_codes),
        "requires_provider_review": run.requires_provider_review,
        "verifier_version": run.verifier_version,
    }


def pause_email_verification(
    *, organization_id: uuid.UUID, run_id: uuid.UUID
) -> EmailVerificationRun:
    organization_id = _native_uuid(organization_id, "organization_id")
    run_id = _native_uuid(run_id, "run_id")
    with tenant_atomic(organization_id):
        run = EmailVerificationRun.objects.select_for_update().filter(
            organization_id=organization_id,
            id=run_id,
        ).first()
        if run is None:
            raise ValidationError("Verification run is unavailable.")
        if run.state not in {
            EmailVerificationRun.State.SUCCEEDED,
            EmailVerificationRun.State.PAUSED,
        }:
            run.state = EmailVerificationRun.State.PAUSED
            run.claim_token = None
            run.save(update_fields=["state", "claim_token", "updated_at"])
        return run


def resume_email_verification(
    *, organization_id: uuid.UUID, run_id: uuid.UUID, dispatch: bool = True
) -> EmailVerificationRun:
    organization_id = _native_uuid(organization_id, "organization_id")
    run_id = _native_uuid(run_id, "run_id")
    with tenant_atomic(organization_id):
        run = EmailVerificationRun.objects.select_for_update().filter(
            organization_id=organization_id,
            id=run_id,
        ).first()
        if run is None:
            raise ValidationError("Verification run is unavailable.")
        if run.state in {
            EmailVerificationRun.State.PAUSED,
            EmailVerificationRun.State.FAILED,
        }:
            run.state = EmailVerificationRun.State.PENDING
            run.claim_token = None
            run.safe_error_code = ""
            run.save(
                update_fields=[
                    "state",
                    "claim_token",
                    "safe_error_code",
                    "updated_at",
                ]
            )
            if dispatch:
                from .tasks import run_email_verification

                dispatch_task_on_commit(
                    run_email_verification,
                    str(organization_id),
                    str(run.id),
                )
        return run
