import pytest
from django.db import connection

from apps.growth.email_verification import (
    BasicSMTPProbe,
    DnsAssessment,
    LocalVerifier,
    SMTPAssessment,
    SMTPDisposition,
    SystemDnsResolver,
    VerificationHistory,
    VerificationStatus,
)


class FakeResolver:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def resolve(self, domain):
        self.calls.append((domain, connection.in_atomic_block))
        return self.result


class FakeSMTPProbe:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def probe(self, *, email, mx_host):
        self.calls.append((email, mx_host, connection.in_atomic_block))
        return self.result


class AllowDomain:
    def acquire(self, domain):
        return True


class FakeMXAddressResolver:
    def __init__(self, addresses):
        self.addresses = addresses
        self.calls = []

    def resolve(self, mx_host):
        self.calls.append(mx_host)
        return self.addresses


def verifier(*, dns=None, smtp=None, limiter=None):
    return LocalVerifier(
        resolver=FakeResolver(
            dns or DnsAssessment(domain_exists=True, mx_hosts=("mx.example.com",))
        ),
        smtp_probe=FakeSMTPProbe(
            smtp
            or SMTPAssessment(
                disposition=SMTPDisposition.ACCEPTED,
                response_code=250,
                catch_all=False,
            )
        ),
        domain_limiter=limiter or AllowDomain(),
    )


@pytest.mark.parametrize("email", ["", "not-an-email", "a@", "a@bad_domain.test", 1, None])
def test_invalid_format_is_fail_closed_without_network(email):
    local = verifier()

    result = local.verify(email)

    assert result.status == VerificationStatus.INVALID
    assert result.reason_codes == ("INVALID_FORMAT",)
    assert local.resolver.calls == []
    assert local.smtp_probe.calls == []


@pytest.mark.parametrize(
    ("dns", "reason"),
    [
        (DnsAssessment(domain_exists=False), "DOMAIN_NOT_FOUND"),
        (DnsAssessment(domain_exists=True, mx_hosts=()), "NO_MX"),
        (DnsAssessment(domain_exists=True, null_mx=True), "NULL_MX"),
    ],
)
def test_domain_and_mx_failures_are_invalid_without_smtp(dns, reason):
    local = verifier(dns=dns)

    result = local.verify("buyer@example.com")

    assert result.status == VerificationStatus.INVALID
    assert reason in result.reason_codes
    assert local.smtp_probe.calls == []


def test_disposable_and_role_mailboxes_are_quality_risks_not_false_invalids():
    disposable = verifier().verify("buyer@mailinator.com")
    role = verifier().verify("sales@example.com")

    assert disposable.status == VerificationStatus.RISKY
    assert "DISPOSABLE_DOMAIN" in disposable.reason_codes
    assert role.status == VerificationStatus.LIKELY_VALID
    assert "ROLE_MAILBOX" in role.reason_codes
    assert role.contact_quality_score < role.deliverability_score


def test_smtp_accepted_is_only_likely_valid_and_catch_all_is_risky():
    accepted = verifier().verify("amy.lee@example.com", contact_name="Amy Lee")
    catch_all = verifier(
        smtp=SMTPAssessment(
            disposition=SMTPDisposition.ACCEPTED,
            response_code=250,
            catch_all=True,
        )
    ).verify("amy.lee@example.com", contact_name="Amy Lee")

    assert accepted.status == VerificationStatus.LIKELY_VALID
    assert "SMTP_ACCEPTED_NOT_PROOF" in accepted.reason_codes
    assert "NAME_PATTERN_MATCH" in accepted.reason_codes
    assert catch_all.status == VerificationStatus.RISKY
    assert "CATCH_ALL" in catch_all.reason_codes


@pytest.mark.parametrize(
    ("smtp", "status", "reason"),
    [
        (
            SMTPAssessment(disposition=SMTPDisposition.REJECTED, response_code=550),
            VerificationStatus.INVALID,
            "SMTP_RECIPIENT_REJECTED",
        ),
        (
            SMTPAssessment(disposition=SMTPDisposition.TIMEOUT),
            VerificationStatus.UNKNOWN,
            "SMTP_TIMEOUT",
        ),
        (
            SMTPAssessment(disposition=SMTPDisposition.TEMPORARY, response_code=451),
            VerificationStatus.UNKNOWN,
            "SMTP_GREYLISTED",
        ),
        (
            SMTPAssessment(disposition=SMTPDisposition.AMBIGUOUS, response_code=252),
            VerificationStatus.UNKNOWN,
            "SMTP_AMBIGUOUS",
        ),
        (
            SMTPAssessment(disposition=SMTPDisposition.BLOCKED),
            VerificationStatus.UNKNOWN,
            "SMTP_TARGET_BLOCKED",
        ),
    ],
)
def test_smtp_outcomes_are_explainable(smtp, status, reason):
    result = verifier(smtp=smtp).verify("buyer@example.com")

    assert result.status == status
    assert reason in result.reason_codes


def test_domain_limit_prevents_smtp_and_returns_unknown():
    class DenyDomain:
        def acquire(self, domain):
            return False

    local = verifier(limiter=DenyDomain())

    result = local.verify("buyer@example.com")

    assert result.status == VerificationStatus.UNKNOWN
    assert "DOMAIN_RATE_LIMITED" in result.reason_codes
    assert local.smtp_probe.calls == []


def test_history_reply_and_unclassified_bounce_adjust_weak_smtp_signal():
    reply = verifier().verify(
        "buyer@example.com",
        history=VerificationHistory(replied=True, sent_count=2),
    )
    bounce = verifier().verify(
        "buyer@example.com",
        history=VerificationHistory(bounced=True, sent_count=1),
    )

    assert reply.status == VerificationStatus.VALID
    assert "HISTORICAL_REPLY" in reply.reason_codes
    assert bounce.status == VerificationStatus.RISKY
    assert "HISTORICAL_BOUNCE_UNCLASSIFIED" in bounce.reason_codes


def test_catch_all_never_becomes_valid_even_with_positive_history():
    catch_all = SMTPAssessment(
        disposition=SMTPDisposition.ACCEPTED,
        response_code=250,
        catch_all=True,
    )

    result = verifier(smtp=catch_all).verify(
        "buyer@example.com",
        history=VerificationHistory(replied=True),
    )

    assert result.status != VerificationStatus.VALID
    assert result.status == VerificationStatus.RISKY


def test_historical_reply_cannot_override_current_recipient_rejection():
    result = verifier(
        smtp=SMTPAssessment(
            disposition=SMTPDisposition.REJECTED,
            response_code=550,
        )
    ).verify(
        "buyer@example.com",
        history=VerificationHistory(replied=True),
    )

    assert result.status == VerificationStatus.INVALID
    assert result.deliverability_score == 5
    assert "SMTP_RECIPIENT_REJECTED" in result.reason_codes
    assert "HISTORICAL_REPLY" in result.reason_codes


def test_corporate_domain_and_name_pattern_are_scored_separately():
    matched = verifier().verify(
        "amy.lee@example.com",
        contact_name="Amy Lee",
        corporate_domain="example.com",
    )
    mismatch = verifier().verify(
        "random@other.example",
        contact_name="Amy Lee",
        corporate_domain="example.com",
    )

    assert matched.deliverability_score == mismatch.deliverability_score
    assert matched.contact_quality_score > mismatch.contact_quality_score
    assert "CORPORATE_DOMAIN_MISMATCH" in mismatch.reason_codes


def test_smtp_probe_checks_recipient_and_random_catch_all_without_sending_data(monkeypatch):
    class SMTPBoundary:
        def __init__(self):
            self.calls = []
            self.rcpt_responses = [(250, b"accepted"), (550, b"rejected")]

        def connect(self, host, port):
            self.calls.append(("connect", host, port))

        def ehlo_or_helo_if_needed(self):
            self.calls.append(("hello",))

        def mail(self, sender):
            self.calls.append(("mail", sender))

        def rcpt(self, recipient):
            self.calls.append(("rcpt", recipient))
            return self.rcpt_responses.pop(0)

        def rset(self):
            self.calls.append(("rset",))

        def quit(self):
            self.calls.append(("quit",))

        def close(self):
            self.calls.append(("close",))

    boundary = SMTPBoundary()
    monkeypatch.setattr(
        "apps.growth.email_verification.smtplib.SMTP",
        lambda timeout: boundary,
    )

    address_resolver = FakeMXAddressResolver(("1.1.1.1",))
    result = BasicSMTPProbe(
        timeout=1,
        retries=0,
        address_resolver=address_resolver,
    ).probe(
        email="buyer@example.com",
        mx_host="mx.example.com",
    )

    assert result.disposition == SMTPDisposition.ACCEPTED
    assert result.catch_all is False
    assert address_resolver.calls == ["mx.example.com"]
    assert boundary.calls[0] == ("connect", "1.1.1.1", 25)
    assert [call[0] for call in boundary.calls] == [
        "connect",
        "hello",
        "mail",
        "rcpt",
        "rset",
        "mail",
        "rcpt",
        "quit",
    ]
    assert not any(call[0] in {"data", "sendmail"} for call in boundary.calls)


@pytest.mark.parametrize("catch_all_code", [421, 450, 451, 252, 354])
def test_smtp_probe_keeps_uncertain_catch_all_response_unknown(
    monkeypatch,
    catch_all_code,
):
    class SMTPBoundary:
        def __init__(self, timeout):
            del timeout
            self.responses = [(250, b"accepted"), (catch_all_code, b"uncertain")]

        def connect(self, host, port):
            del host, port

        def ehlo_or_helo_if_needed(self):
            return None

        def mail(self, sender):
            del sender

        def rcpt(self, recipient):
            del recipient
            return self.responses.pop(0)

        def rset(self):
            return None

        def quit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("apps.growth.email_verification.smtplib.SMTP", SMTPBoundary)

    assessment = BasicSMTPProbe(
        timeout=1,
        retries=0,
        address_resolver=FakeMXAddressResolver(("1.1.1.1",)),
    ).probe(email="buyer@example.com", mx_host="mx.example.com")
    result = verifier(smtp=assessment).verify("buyer@example.com")

    assert assessment.catch_all is None
    assert result.status == VerificationStatus.UNKNOWN
    assert "CATCH_ALL_UNKNOWN" in result.reason_codes


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("::1",),
        ("169.254.10.20",),
        ("224.0.0.1",),
        ("239.255.255.250",),
        ("ff02::1",),
        ("ff0e::1",),
        ("fec0::1",),
        ("feff:ffff::1",),
        ("1.1.1.1", "10.0.0.1"),
    ],
)
def test_smtp_probe_rejects_non_public_or_mixed_mx_addresses(monkeypatch, addresses):
    smtp_created = []
    monkeypatch.setattr(
        "apps.growth.email_verification.smtplib.SMTP",
        lambda timeout: smtp_created.append(timeout),
    )

    result = BasicSMTPProbe(
        timeout=1,
        retries=0,
        address_resolver=FakeMXAddressResolver(addresses),
    ).probe(email="buyer@example.com", mx_host="mx.example.com")

    assert result.disposition == SMTPDisposition.BLOCKED
    assert smtp_created == []


def test_smtp_probe_retries_only_within_the_bounded_budget(monkeypatch):
    calls = []

    class TimeoutSMTP:
        def __init__(self, timeout):
            calls.append(timeout)

        def connect(self, host, port):
            raise TimeoutError("safe test timeout")

        def quit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("apps.growth.email_verification.smtplib.SMTP", TimeoutSMTP)

    result = BasicSMTPProbe(
        timeout=1,
        retries=1,
        address_resolver=FakeMXAddressResolver(("1.1.1.1",)),
    ).probe(
        email="buyer@example.com",
        mx_host="mx.example.com",
    )

    assert result.disposition == SMTPDisposition.TIMEOUT
    assert calls == [1, 1]


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: SystemDnsResolver(timeout=60, lifetime=60), "DNS timeout"),
        (lambda: BasicSMTPProbe(timeout=60, retries=0), "SMTP timeout"),
        (lambda: BasicSMTPProbe(timeout=1, retries=100), "SMTP retries"),
    ],
)
def test_network_budgets_reject_unbounded_configuration(factory, message):
    with pytest.raises(ValueError, match=message):
        factory()
