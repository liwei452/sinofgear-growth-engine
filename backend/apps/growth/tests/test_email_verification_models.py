import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.growth.models import (
    Contact,
    DiscoveryCandidate,
    EmailVerificationEvidence,
    EmailVerificationRun,
    TargetAccount,
)
from apps.identity.models import Organization


pytestmark = pytest.mark.django_db


def make_run(organization, **overrides):
    email = overrides.pop("normalized_email", "buyer@example.com")
    values = {
        "organization": organization,
        "normalized_email": email,
        "email_fingerprint": hashlib.sha256(email.encode()).hexdigest(),
        "domain": email.rsplit("@", 1)[-1],
        "idempotency_key": "verify:buyer@example.com:v1",
        **overrides,
    }
    return EmailVerificationRun.objects.create(**values)


def test_run_has_organization_scoped_idempotency_and_separate_scores():
    first = Organization.objects.create(name="First", slug="email-first")
    second = Organization.objects.create(name="Second", slug="email-second")
    make_run(first)
    make_run(second)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_run(first)

    run = EmailVerificationRun.objects.get(organization=first)
    run.state = EmailVerificationRun.State.SUCCEEDED
    run.result_status = EmailVerificationRun.ResultStatus.LIKELY_VALID
    run.deliverability_score = 78
    run.contact_quality_score = 42
    run.reason_codes = ["ROLE_MAILBOX"]
    run.full_clean()


def test_optional_contact_and_candidate_must_share_the_run_organization():
    own = Organization.objects.create(name="Own", slug="email-own")
    other = Organization.objects.create(name="Other", slug="email-other")
    account = TargetAccount.objects.create(organization=other, name="Other", country="US")
    contact = Contact.objects.create(organization=other, account=account, full_name="Buyer")
    candidate = DiscoveryCandidate.objects.create(
        organization=other,
        company_name="Other Candidate",
        country="US",
        import_format="CSV",
        source_governance={},
        raw_record={},
        record_hash="a" * 64,
    )

    run = EmailVerificationRun(
        organization=own,
        contact=contact,
        candidate=candidate,
        normalized_email="buyer@example.com",
        email_fingerprint="b" * 64,
        domain="example.com",
        idempotency_key="cross-tenant",
    )

    with pytest.raises(ValidationError, match="same organization"):
        run.full_clean()

    with pytest.raises(ValidationError, match="same organization"):
        EmailVerificationRun.objects.create(
            organization=own,
            contact=contact,
            candidate=candidate,
            normalized_email="buyer@example.com",
            email_fingerprint="c" * 64,
            domain="example.com",
            idempotency_key="cross-tenant-create",
        )


def test_evidence_is_append_only_and_carries_source_time_and_version():
    organization = Organization.objects.create(name="Evidence", slug="email-evidence")
    run = make_run(organization)
    item = EmailVerificationEvidence.objects.create(
        organization=organization,
        run=run,
        sequence=1,
        check_type="MX",
        source="DNS",
        source_version="local-email-v1",
        outcome="PASS",
        reason_code="MX_FOUND",
        evidence={"mx_count": 2},
    )

    assert item.observed_at is not None
    item.outcome = "FAIL"
    with pytest.raises(ValidationError, match="immutable"):
        item.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        item.delete()


@pytest.mark.parametrize("operation", ["update", "bulk_update", "delete"])
def test_evidence_queryset_mutations_are_rejected(operation):
    organization = Organization.objects.create(
        name=f"Evidence {operation}",
        slug=f"email-evidence-{operation}",
    )
    run = make_run(organization)
    item = EmailVerificationEvidence.objects.create(
        organization=organization,
        run=run,
        sequence=1,
        check_type="MX",
        source="DNS",
        source_version="local-email-v1",
        outcome="PASS",
        reason_code="MX_FOUND",
        evidence={"mx_count": 1},
    )

    with pytest.raises(ValidationError, match="append-only"):
        if operation == "update":
            EmailVerificationEvidence.objects.filter(id=item.id).update(
                outcome="FAIL"
            )
        elif operation == "bulk_update":
            item.outcome = "FAIL"
            EmailVerificationEvidence.objects.bulk_update([item], ["outcome"])
        else:
            EmailVerificationEvidence.objects.filter(id=item.id).delete()

    item.refresh_from_db()
    assert item.outcome == "PASS"


def test_completed_run_requires_valid_result_scores_and_reason_codes():
    organization = Organization.objects.create(name="Validation", slug="email-validation")
    run = EmailVerificationRun(
        organization=organization,
        normalized_email="buyer@example.com",
        email_fingerprint="not-a-hash",
        domain="example.com",
        idempotency_key="invalid-result",
        state=EmailVerificationRun.State.SUCCEEDED,
        result_status=EmailVerificationRun.ResultStatus.VALID,
        deliverability_score=101,
        contact_quality_score=80,
        reason_codes=["", 1],
    )

    with pytest.raises(ValidationError) as exc_info:
        run.full_clean()

    assert {"email_fingerprint", "deliverability_score", "reason_codes"} <= set(
        exc_info.value.message_dict
    )
