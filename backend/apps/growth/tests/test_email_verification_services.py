from datetime import UTC, datetime, timedelta
import uuid

import pytest
from django.test import override_settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

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
    verify_email_for_tenant,
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


def test_history_is_bound_to_the_exact_mailbox_not_every_message_on_account():
    organization = Organization.objects.create(
        name="Exact History",
        slug="email-exact-history",
    )
    account = TargetAccount.objects.create(
        organization=organization,
        name="Acme",
        country="US",
    )
    target_message = OutreachMessage.objects.create(
        organization=organization,
        account=account,
        provider="smtp",
        status=OutreachMessage.Status.REPLIED,
        payload={"email": "buyer@example.com"},
    )
    other_message = OutreachMessage.objects.create(
        organization=organization,
        account=account,
        provider="smtp",
        status=OutreachMessage.Status.BOUNCED,
        payload={"email": "other@example.com"},
    )
    now = timezone.now()
    OutreachMessage.objects.filter(id=target_message.id).update(
        created_at=now - timedelta(minutes=1)
    )
    OutreachMessage.objects.filter(id=other_message.id).update(created_at=now)
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="history-exact-mailbox",
        dispatch=False,
    )
    verifier = RecordingVerifier()

    execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    history = verifier.calls[0]["kwargs"]["history"]
    assert history.replied is True
    assert history.bounced is False
    assert history.sent_count == 0


def test_invalid_local_result_is_idempotent():
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
    result = execute_email_verification(
        organization_id=organization.id,
        run_id=first.id,
        local_verifier=RecordingVerifier(local_result(VerificationStatus.INVALID)),
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert result.result_status == EmailVerificationRun.ResultStatus.INVALID


def test_automatic_idempotency_tracks_scoring_inputs_history_and_refresh():
    organization = Organization.objects.create(
        name="Context Idempotency",
        slug="email-context-idempotency",
    )
    account = TargetAccount.objects.create(
        organization=organization,
        name="Acme",
        country="US",
    )

    first = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="example.com",
        high_value=False,
        local_verifier=RecordingVerifier(),
    )
    same = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="example.com",
        high_value=False,
        local_verifier=RecordingVerifier(),
    )
    changed_input = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="other.example",
        high_value=True,
        local_verifier=RecordingVerifier(),
    )
    OutreachMessage.objects.create(
        organization=organization,
        account=account,
        provider="smtp",
        status=OutreachMessage.Status.REPLIED,
        payload={"email": "buyer@example.com"},
    )
    changed_history = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="other.example",
        high_value=True,
        local_verifier=RecordingVerifier(),
    )
    OutreachMessage.objects.create(
        organization=organization,
        account=account,
        provider="smtp",
        status=OutreachMessage.Status.REPLIED,
        payload={"email": "buyer@example.com"},
    )
    newer_same_history_result = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="other.example",
        high_value=True,
        local_verifier=RecordingVerifier(),
    )
    refreshed = verify_email_for_tenant(
        organization_id=organization.id,
        email="buyer@example.com",
        contact_name="Amy Lee",
        corporate_domain="other.example",
        high_value=True,
        force_refresh=True,
        local_verifier=RecordingVerifier(),
    )

    assert same["verification_id"] == first["verification_id"]
    assert changed_input["verification_id"] != first["verification_id"]
    assert changed_history["verification_id"] != changed_input["verification_id"]
    assert newer_same_history_result["verification_id"] != changed_history["verification_id"]
    assert refreshed["verification_id"] != newer_same_history_result["verification_id"]


def test_risky_result_only_marks_future_provider_review_in_a1():
    organization = Organization.objects.create(name="Provider", slug="email-provider")
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="provider-fallback",
        dispatch=False,
    )
    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=RecordingVerifier(local_result(VerificationStatus.RISKY, catch_all=True)),
    )

    assert result.requires_provider_review is True
    assert result.result_source == "LOCAL"


def test_pause_during_local_network_prevents_finalize():
    organization = Organization.objects.create(
        name="Pause Provider",
        slug="email-pause-provider",
    )
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="pause-provider-race",
        dispatch=False,
    )
    verifier = RecordingVerifier(
        result=local_result(VerificationStatus.RISKY, catch_all=True),
        callback=lambda: pause_email_verification(
            organization_id=organization.id,
            run_id=run.id,
        ),
    )

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    assert result.state == EmailVerificationRun.State.PAUSED


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


@override_settings(EMAIL_VERIFICATION_CLAIM_TIMEOUT_SECONDS=60)
def test_stale_running_claim_is_reclaimed_without_old_result_overwrite():
    organization = Organization.objects.create(
        name="Stale Claim",
        slug="email-stale-claim",
    )
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key="stale-claim",
        dispatch=False,
    )
    old_claim = uuid.uuid4()
    EmailVerificationRun.objects.filter(id=run.id).update(
        state=EmailVerificationRun.State.RUNNING,
        claim_token=old_claim,
        attempt_count=1,
        started_at=timezone.now() - timedelta(minutes=5),
    )
    verifier = RecordingVerifier()

    result = execute_email_verification(
        organization_id=organization.id,
        run_id=run.id,
        local_verifier=verifier,
    )

    assert len(verifier.calls) == 1
    assert result.state == EmailVerificationRun.State.SUCCEEDED
    assert result.attempt_count == 2
    assert result.claim_token is None


@pytest.mark.parametrize("claim_timeout", [29, 3601])
def test_claim_timeout_rejects_values_outside_safe_bounds(claim_timeout):
    organization = Organization.objects.create(
        name=f"Invalid Claim {claim_timeout}",
        slug=f"email-invalid-claim-{claim_timeout}",
    )
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key=f"invalid-claim-{claim_timeout}",
        dispatch=False,
    )

    with override_settings(EMAIL_VERIFICATION_CLAIM_TIMEOUT_SECONDS=claim_timeout):
        EmailVerificationRun.objects.filter(id=run.id).update(
            state=EmailVerificationRun.State.RUNNING,
            claim_token=uuid.uuid4(),
            started_at=timezone.now(),
        )
        with pytest.raises(EmailVerificationExecutionError, match="claim_timeout_invalid"):
            execute_email_verification(
                organization_id=organization.id,
                run_id=run.id,
                local_verifier=RecordingVerifier(),
            )


@pytest.mark.parametrize("claim_timeout", [30, 3600])
def test_claim_timeout_accepts_inclusive_safe_bounds(claim_timeout):
    organization = Organization.objects.create(
        name=f"Valid Claim {claim_timeout}",
        slug=f"email-valid-claim-{claim_timeout}",
    )
    run, _ = request_email_verification(
        organization_id=organization.id,
        email="buyer@example.com",
        idempotency_key=f"valid-claim-{claim_timeout}",
        dispatch=False,
    )
    verifier = RecordingVerifier()

    with override_settings(EMAIL_VERIFICATION_CLAIM_TIMEOUT_SECONDS=claim_timeout):
        EmailVerificationRun.objects.filter(id=run.id).update(
            state=EmailVerificationRun.State.RUNNING,
            claim_token=uuid.uuid4(),
            started_at=timezone.now(),
        )
        result = execute_email_verification(
            organization_id=organization.id,
            run_id=run.id,
            local_verifier=verifier,
        )

    assert result.state == EmailVerificationRun.State.RUNNING
    assert verifier.calls == []
