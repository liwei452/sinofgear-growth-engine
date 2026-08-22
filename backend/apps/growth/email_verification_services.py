from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.common.tenancy import tenant_atomic
from apps.common.tenant_tasks import dispatch_task_on_commit

from .email_verification import (
    EmailVerificationProvider,
    LocalVerificationResult,
    VerificationHistory,
    VerificationStatus,
    get_local_verifier,
    get_verification_provider,
)
from .growth_events import EVENT_EMAIL_FAILED, EVENT_EMAIL_SENT
from .models import (
    Contact,
    DiscoveryCandidate,
    EmailVerificationEvidence,
    EmailVerificationRun,
    GrowthEvent,
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
    idempotency_key: str,
    contact_id: uuid.UUID | None = None,
    candidate_id: uuid.UUID | None = None,
    contact_name: str = "",
    corporate_domain: str = "",
    high_value: bool = False,
    dispatch: bool = True,
) -> tuple[EmailVerificationRun, bool]:
    organization_id = _native_uuid(organization_id, "organization_id")
    if type(idempotency_key) is not str or not idempotency_key.strip():
        raise ValidationError("idempotency_key is required.")
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
        safe_snapshot = {
            "contact_name": (contact_name or (contact.full_name if contact else "")).strip(),
            "corporate_domain": corporate_domain.strip().lower().rstrip("."),
            "high_value": high_value,
        }
        run, created = EmailVerificationRun.objects.get_or_create(
            organization_id=organization_id,
            idempotency_key=idempotency_key.strip(),
            defaults={
                "contact": contact,
                "candidate": candidate,
                "normalized_email": normalized,
                "email_fingerprint": fingerprint,
                "domain": domain,
                "request_snapshot": safe_snapshot,
            },
        )
        if not created and (
            run.normalized_email != normalized
            or run.contact_id != (contact.id if contact else None)
            or run.candidate_id != (candidate.id if candidate else None)
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
    account_ids = set(
        GrowthEvent.objects.filter(
            organization_id=organization_id,
            event_type__in=[EVENT_EMAIL_SENT, EVENT_EMAIL_FAILED],
            payload__email=email,
        ).values_list("entity_id", flat=True)
    )
    direct_account_ids = OutreachMessage.objects.filter(
        organization_id=organization_id,
        payload__email=email,
    ).values_list("account_id", flat=True)
    account_ids.update(str(value) for value in direct_account_ids)
    messages = OutreachMessage.objects.filter(
        organization_id=organization_id,
        account_id__in=account_ids,
    ).order_by("-created_at", "-id")
    latest = messages.first()
    return VerificationHistory(
        replied=bool(latest and latest.status == OutreachMessage.Status.REPLIED),
        bounced=bool(latest and latest.status == OutreachMessage.Status.BOUNCED),
        sent_count=messages.filter(status=OutreachMessage.Status.SENT).count(),
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
        if run.state in {
            EmailVerificationRun.State.RUNNING,
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
        prepared = PreparedEmailVerification(
            run_id=run.id,
            claim_token=claim_token,
            email=run.normalized_email,
            contact_name=str(snapshot.get("contact_name") or ""),
            corporate_domain=str(snapshot.get("corporate_domain") or ""),
            high_value=snapshot.get("high_value") is True,
            history=_verification_history(organization_id, run.normalized_email),
        )
        return run, prepared


def _provider_is_needed(result: LocalVerificationResult, *, high_value: bool) -> bool:
    return bool(
        high_value
        or result.catch_all
        or result.status in {VerificationStatus.RISKY, VerificationStatus.UNKNOWN}
    )


def _safe_provider_result(provider_result: object) -> tuple[str, ...]:
    if not isinstance(provider_result, dict):
        return ("PROVIDER_RESULT_UNUSABLE",)
    status = provider_result.get("status")
    if status not in {item.value for item in VerificationStatus}:
        return ("PROVIDER_RESULT_UNUSABLE",)
    codes = provider_result.get("reason_codes", [])
    if not isinstance(codes, list):
        return ("PROVIDER_RESULT_UNUSABLE",)
    return tuple(
        code for code in codes if isinstance(code, str) and code.strip()
    )[:10]


def _finalize_email_verification(
    *,
    organization_id: uuid.UUID,
    prepared: PreparedEmailVerification,
    local_result: LocalVerificationResult,
    provider_codes: tuple[str, ...],
    provider_called: bool,
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
        run.reason_codes = list(dict.fromkeys((*local_result.reason_codes, *provider_codes)))
        run.requires_provider_review = _provider_is_needed(
            local_result, high_value=prepared.high_value
        )
        run.result_source = "LOCAL_WITH_PROVIDER" if provider_called else "LOCAL"
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
    provider: EmailVerificationProvider | None = None,
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
        provider = provider if provider is not None else get_verification_provider()
        provider_called = False
        provider_codes: tuple[str, ...] = ()
        if (
            local_result.status != VerificationStatus.INVALID
            and _provider_is_needed(local_result, high_value=prepared.high_value)
            and provider is not None
        ):
            provider_called = True
            provider_codes = _safe_provider_result(provider.verify(prepared.email))
    except Exception:
        _finalize_failure(organization_id=organization_id, prepared=prepared)
        raise EmailVerificationExecutionError("verification_network_failed") from None
    return _finalize_email_verification(
        organization_id=organization_id,
        prepared=prepared,
        local_result=local_result,
        provider_codes=provider_codes,
        provider_called=provider_called,
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
    local_verifier: LocalVerifierLike | None = None,
    provider: EmailVerificationProvider | None = None,
) -> dict:
    normalized = normalize_email(email)
    fingerprint = hashlib.sha256(normalized.encode()).hexdigest()
    subject = candidate_id or contact_id or "address"
    idempotency_key = f"email-verify:{subject}:{fingerprint}"
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
        provider=provider,
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
