from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.growth.email_verification import (
    LocalVerificationResult,
    VerificationEvidence,
    VerificationStatus,
)
from apps.growth.email_verification_services import (
    EmailVerificationExecutionError,
    execute_email_verification,
    pause_email_verification,
    request_email_verification,
    resume_email_verification,
)
from apps.growth.models import (
    Contact,
    DiscoveryCandidate,
    EmailVerificationRun,
    OutreachMessage,
    TargetAccount,
)
from apps.identity.models import Organization


pytestmark = pytest.mark.django_db(transaction=True)


def local_result(status=VerificationStatus.LIKELY_VALID, *, catch_all=False):
    reason = "CATCH_ALL" if catch_all else "SMTP_ACCEPTED_NOT_PROOF"
    return LocalVerificationResult(
        email="buyer@example.com",
        status=status,
        deliverability_score=70,
        contact_quality_score=80,
        reason_codes=(reason,),
        evidence=(
            VerificationEvidence(
                check_type="SMTP",
                source="SMTP_RCPT",
                source_version="local-email-v1",
                outcome="ACCEPTED",
                reason_code=reason,
                observed_at=datetime.now(UTC),
                details={"response_code": 250},
            ),
        ),
        catch_all=catch_all,
    )


class RecordingVerifier:
    def __init__(self, result=None, callback=None):
        self.result = result or local_result()
        self.callback = callback
        self.calls = []

    def verify(self, email, **kwargs):
        self.calls.append(
            {
                "email": email,
                "kwargs": kwargs,
                "in_atomic": connection.in_atomic_block,
            }
        )
        if self.callback:
            self.callback()
        return self.result


class RecordingProvider:
    def __init__(self):
        self.calls = []

    def verify(self, email):
        self.calls.append((email, connection.in_atomic_block))
        return {"status": "LIKELY_VALID", "reason_codes": ["PROVIDER_CORROBORATED"]}


def test_prepare_and_finalize_use_tenant_transactions_but_network_does_not():
    organization = Organization.objects.create(name="Phased", slug="email-phased")
    run, created = request_email_verification(
        organization_id=organization.id,
        email=" Buyer@Example.com ",
        idempotency_key="phase-boundary",
        dispatch=False,
    )
    verifier = RecordingVerifier()

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    assert created is True
    assert verifier.calls == [
        {
            "email": "buyer@example.com",
            "kwargs": {
                "contact_name": "",
                "corporate_domain": "",
                "history": verifier.calls[0]["kwargs"]["history"],
            },
            "in_atomic": False,
        }
    ]
    assert result.state == EmailVerificationRun.State.SUCCEEDED
    assert result.evidence_items.count() == 1


def test_history_bounce_is_frozen_in_prepare_and_changes_local_result():
    organization = Organization.objects.create(name="History", slug="email-history")
    account = TargetAccount.objects.create(organization=organization, name="Acme", country="US")
    OutreachMessage.objects.create(
        organization=organization,
        account=account,
        provider="smtp",
        status=OutreachMessage.Status.BOUNCED,
        payload={"email": "buyer@example.com"},
    )
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="history-bounce",
        dispatch=False,
    )
    verifier = RecordingVerifier()

    execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    assert verifier.calls[0]["kwargs"]["history"].bounced is True


def test_invalid_local_result_never_calls_optional_provider_and_request_is_idempotent():
    organization = Organization.objects.create(name="Fallback", slug="email-fallback")
    first, first_created = request_email_verification(
        organization_id=organization.id,
        email="bad-address",
        idempotency_key="same-request",
        dispatch=False,
    )
    second, second_created = request_email_verification(
        organization_id=organization.id,
        email="bad-address",
        idempotency_key="same-request",
        dispatch=False,
    )
    provider = RecordingProvider()

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=first.id,
        local_verifier=RecordingVerifier(local_result(VerificationStatus.INVALID)),
        provider=provider,
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert result.result_status == EmailVerificationRun.ResultStatus.INVALID
    assert provider.calls == []


def test_risky_result_marks_fallback_and_provider_runs_outside_transaction():
    organization = Organization.objects.create(name="Provider", slug="email-provider")
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="provider-fallback",
        dispatch=False,
    )
    provider = RecordingProvider()

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=RecordingVerifier(local_result(VerificationStatus.RISKY, catch_all=True)),
        provider=provider,
    )

    assert provider.calls == [("buyer@example.com", False)]
    assert result.requires_provider_review is True
    assert result.result_source == "LOCAL_WITH_PROVIDER"


def test_pause_during_network_makes_old_finalize_a_noop():
    organization = Organization.objects.create(name="Pause", slug="email-pause")
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="pause-race",
        dispatch=False,
    )
    verifier = RecordingVerifier(
        callback=lambda: pause_email_verification(
            organization_id=organization.id,
            run_id=run.id,
        )
    )

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    assert result.state == EmailVerificationRun.State.PAUSED
    assert result.evidence_items.count() == 0


def test_cross_tenant_parent_and_run_ids_are_rejected_without_leaking():
    own = Organization.objects.create(name="Own", slug="email-service-own")
    other = Organization.objects.create(name="Other", slug="email-service-other")
    account = TargetAccount.objects.create(organization=other, name="Other", country="US")
    contact = Contact.objects.create(organization=other, account=account, full_name="Buyer")
    candidate = DiscoveryCandidate.objects.create(
        organization=other,
        company_name="Other Candidate",
        country="US",
        import_format="CSV",
        source_governance={},
        raw_record={},
        record_hash="f" * 64,
    )

    with pytest.raises(ValidationError, match="unavailable"):
        request_email_verification(
            organization_id=own.id,
            email="buyer@example.com",
            idempotency_key="cross-parent",
            contact_id=contact.id,
            candidate_id=candidate.id,
            dispatch=False,
        )

    other_run, _ = request_email_verification(
        organization_id=other.id,
        email="buyer@example.com",
        idempotency_key="other-run",
        dispatch=False,
    )
    with pytest.raises(ValidationError, match="unavailable"):
        execute_email_verification(
            organization_id=own.id,
            run_id=other_run.id,
            local_verifier=RecordingVerifier(),
        )


def test_network_failure_persists_only_a_safe_code_and_suppresses_raw_error():
    organization = Organization.objects.create(name="Safe Failure", slug="email-safe-failure")
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="safe-failure",
        dispatch=False,
    )

    class FailingVerifier:
        def verify(self, email, **kwargs):
            raise RuntimeError("provider secret-token raw response")

    with pytest.raises(EmailVerificationExecutionError) as exc_info:
        execute_email_verification(
            organization_id=organization.id,
            run_id=run.id,
            local_verifier=FailingVerifier(),
        )

    assert str(exc_info.value) == "verification_network_failed"
    assert exc_info.value.__cause__ is None
    run.refresh_from_db()
    assert run.state == EmailVerificationRun.State.FAILED
    assert run.safe_error_code == "VERIFICATION_NETWORK_FAILED"
    assert "secret-token" not in run.safe_error_code


def test_paused_run_can_be_explicitly_resumed_without_changing_identity():
    organization = Organization.objects.create(name="Resume", slug="email-resume")
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="resume-run",
        dispatch=False,
    )
    pause_email_verification(organization_id=organization.id, run_id=run.id)

    resumed = resume_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        dispatch=False,
    )
    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=RecordingVerifier(),
    )

    assert resumed.id == run.id
    assert result.state == EmailVerificationRun.State.SUCCEEDED
