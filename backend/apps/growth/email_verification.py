from __future__ import annotations

import hashlib
import ipaddress
import math
import re
import smtplib
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from django.conf import settings
from django.core.cache import cache


EMAIL_RE = re.compile(
    r"^(?=.{3,320}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
VERIFIER_VERSION = "local-email-v1"
ROLE_LOCAL_PARTS = frozenset(
    {
        "admin",
        "billing",
        "contact",
        "enquiries",
        "hello",
        "info",
        "office",
        "orders",
        "procurement",
        "sales",
        "support",
    }
)
DISPOSABLE_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "temp-mail.org",
        "yopmail.com",
    }
)
IPV4_SHARED_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _bounded_float(value: object, *, name: str, minimum: float, maximum: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum} seconds.")
    return parsed


def _bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


class VerificationStatus(StrEnum):
    VALID = "VALID"
    LIKELY_VALID = "LIKELY_VALID"
    RISKY = "RISKY"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class SMTPDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TEMPORARY = "TEMPORARY"
    AMBIGUOUS = "AMBIGUOUS"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class DnsAssessment:
    domain_exists: bool
    mx_hosts: tuple[str, ...] = ()
    null_mx: bool = False


@dataclass(frozen=True, slots=True)
class SMTPAssessment:
    disposition: SMTPDisposition
    response_code: int | None = None
    catch_all: bool | None = None


@dataclass(frozen=True, slots=True)
class VerificationHistory:
    replied: bool = False
    bounced: bool = False
    sent_count: int = 0
    source_fingerprint: str = ""


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    check_type: str
    source: str
    source_version: str
    outcome: str
    reason_code: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        result = asdict(self)
        result["observed_at"] = self.observed_at.isoformat()
        return result


@dataclass(frozen=True, slots=True)
class LocalVerificationResult:
    email: str
    status: VerificationStatus
    deliverability_score: int
    contact_quality_score: int
    reason_codes: tuple[str, ...]
    evidence: tuple[VerificationEvidence, ...]
    verifier_version: str = VERIFIER_VERSION
    catch_all: bool | None = None

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "status": self.status.value,
            "deliverability_score": self.deliverability_score,
            "contact_quality_score": self.contact_quality_score,
            "reason_codes": list(self.reason_codes),
            "evidence": [item.as_dict() for item in self.evidence],
            "verifier_version": self.verifier_version,
            "catch_all": self.catch_all,
        }


class DnsResolver(Protocol):
    def resolve(self, domain: str) -> DnsAssessment: ...


class SMTPProbe(Protocol):
    def probe(self, *, email: str, mx_host: str) -> SMTPAssessment: ...


class MXAddressResolver(Protocol):
    def resolve(self, mx_host: str) -> tuple[str, ...]: ...


class DomainLimiter(Protocol):
    def acquire(self, domain: str) -> bool: ...


class EmailVerificationProvider(Protocol):
    def verify(self, email: str) -> dict: ...


class SystemDnsResolver:
    def __init__(self, *, timeout: float | None = None, lifetime: float | None = None):
        self.timeout = _bounded_float(
            timeout
            if timeout is not None
            else getattr(settings, "EMAIL_VERIFICATION_DNS_TIMEOUT_SECONDS", 3.0),
            name="DNS timeout",
            minimum=0.1,
            maximum=10.0,
        )
        self.lifetime = _bounded_float(
            lifetime
            if lifetime is not None
            else getattr(settings, "EMAIL_VERIFICATION_DNS_LIFETIME_SECONDS", 5.0),
            name="DNS lifetime",
            minimum=self.timeout,
            maximum=30.0,
        )

    def resolve(self, domain: str) -> DnsAssessment:
        import dns.exception
        import dns.resolver

        resolver = dns.resolver.Resolver(configure=True)
        resolver.timeout = self.timeout
        resolver.lifetime = self.lifetime
        try:
            answers = resolver.resolve(domain, "MX")
        except dns.resolver.NXDOMAIN:
            return DnsAssessment(domain_exists=False)
        except dns.resolver.NoAnswer:
            return DnsAssessment(domain_exists=True)
        except (dns.exception.Timeout, dns.resolver.NoNameservers, OSError):
            raise TimeoutError("DNS lookup unavailable.") from None
        records = tuple(
            sorted(
                (int(answer.preference), str(answer.exchange).rstrip(".").lower())
                for answer in answers
            )
        )
        null_mx = any(preference == 0 and not host for preference, host in records)
        return DnsAssessment(
            domain_exists=True,
            mx_hosts=tuple(host for _, host in records if host),
            null_mx=null_mx,
        )


class SystemMXAddressResolver:
    def __init__(self, *, timeout: float | None = None, lifetime: float | None = None):
        self.timeout = _bounded_float(
            timeout
            if timeout is not None
            else getattr(settings, "EMAIL_VERIFICATION_DNS_TIMEOUT_SECONDS", 3.0),
            name="DNS timeout",
            minimum=0.1,
            maximum=10.0,
        )
        self.lifetime = _bounded_float(
            lifetime
            if lifetime is not None
            else getattr(settings, "EMAIL_VERIFICATION_DNS_LIFETIME_SECONDS", 5.0),
            name="DNS lifetime",
            minimum=self.timeout,
            maximum=30.0,
        )

    def resolve(self, mx_host: str) -> tuple[str, ...]:
        import dns.exception
        import dns.resolver

        resolver = dns.resolver.Resolver(configure=True)
        resolver.timeout = self.timeout
        resolver.lifetime = self.lifetime
        addresses = set()
        for record_type in ("A", "AAAA"):
            try:
                answers = resolver.resolve(mx_host, record_type)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                continue
            except (dns.exception.Timeout, dns.resolver.NoNameservers, OSError):
                raise TimeoutError("MX address lookup unavailable.") from None
            addresses.update(str(answer).strip() for answer in answers)
        return tuple(sorted(addresses))


class BasicSMTPProbe:
    def __init__(
        self,
        *,
        timeout: float | None = None,
        retries: int | None = None,
        address_resolver: MXAddressResolver | None = None,
    ):
        self.timeout = _bounded_float(
            timeout
            if timeout is not None
            else getattr(settings, "EMAIL_VERIFICATION_SMTP_TIMEOUT_SECONDS", 5.0),
            name="SMTP timeout",
            minimum=0.1,
            maximum=15.0,
        )
        self.retries = _bounded_int(
            getattr(settings, "EMAIL_VERIFICATION_SMTP_RETRIES", 1)
            if retries is None
            else retries,
            name="SMTP retries",
            minimum=0,
            maximum=2,
        )
        self.address_resolver = address_resolver or SystemMXAddressResolver()

    def probe(self, *, email: str, mx_host: str) -> SMTPAssessment:
        try:
            addresses = self.address_resolver.resolve(mx_host)
        except TimeoutError:
            return SMTPAssessment(disposition=SMTPDisposition.TIMEOUT)
        if not addresses:
            return SMTPAssessment(disposition=SMTPDisposition.TIMEOUT)
        try:
            parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
        except ValueError:
            return SMTPAssessment(disposition=SMTPDisposition.BLOCKED)
        if any(not self._is_safe_public_target(address) for address in parsed_addresses):
            return SMTPAssessment(disposition=SMTPDisposition.BLOCKED)
        target_ip = str(sorted(parsed_addresses, key=lambda address: (address.version, int(address)))[0])
        for attempt in range(self.retries + 1):
            try:
                return self._probe_once(email=email, target_ip=target_ip)
            except (TimeoutError, socket.timeout, OSError, smtplib.SMTPException):
                if attempt == self.retries:
                    return SMTPAssessment(disposition=SMTPDisposition.TIMEOUT)
        return SMTPAssessment(disposition=SMTPDisposition.TIMEOUT)

    def _probe_once(self, *, email: str, target_ip: str) -> SMTPAssessment:
        smtp = smtplib.SMTP(timeout=self.timeout)
        try:
            smtp.connect(target_ip, 25)
            smtp.ehlo_or_helo_if_needed()
            smtp.mail("")
            response_code, _ = smtp.rcpt(email)
            if 400 <= response_code < 500:
                return SMTPAssessment(
                    disposition=SMTPDisposition.TEMPORARY,
                    response_code=response_code,
                )
            if response_code >= 500:
                return SMTPAssessment(
                    disposition=SMTPDisposition.REJECTED,
                    response_code=response_code,
                )
            if response_code not in {250, 251}:
                return SMTPAssessment(
                    disposition=SMTPDisposition.AMBIGUOUS,
                    response_code=response_code,
                )
            random_email = f"ev-{uuid.uuid4().hex}@{email.rsplit('@', 1)[1]}"
            smtp.rset()
            smtp.mail("")
            catch_all_code, _ = smtp.rcpt(random_email)
            if catch_all_code in {250, 251}:
                catch_all = True
            elif catch_all_code >= 500:
                catch_all = False
            else:
                catch_all = None
            return SMTPAssessment(
                disposition=SMTPDisposition.ACCEPTED,
                response_code=response_code,
                catch_all=catch_all,
            )
        finally:
            try:
                smtp.quit()
            except (OSError, smtplib.SMTPException):
                smtp.close()

    @staticmethod
    def _is_safe_public_target(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if isinstance(address, ipaddress.IPv4Address) and address in IPV4_SHARED_SPACE:
            return False
        return bool(
            address.is_global
            and not address.is_multicast
            and not address.is_unspecified
            and not address.is_reserved
            and not address.is_loopback
            and not address.is_link_local
            and not address.is_private
        )


class CacheDomainLimiter:
    def __init__(self, *, ttl_seconds: int | None = None):
        self.ttl_seconds = _bounded_int(
            getattr(settings, "EMAIL_VERIFICATION_DOMAIN_LOCK_SECONDS", 10)
            if ttl_seconds is None
            else ttl_seconds,
            name="Domain lock",
            minimum=1,
            maximum=300,
        )

    def acquire(self, domain: str) -> bool:
        key = f"email-verification:domain:{hashlib.sha256(domain.encode()).hexdigest()}"
        return bool(cache.add(key, "1", timeout=self.ttl_seconds))


def _normalize_email(value: object) -> str:
    if type(value) is not str:
        return ""
    return value.strip().lower()


def _name_patterns(name: str) -> set[str]:
    parts = [part for part in re.findall(r"[a-z0-9]+", name.casefold()) if part]
    if len(parts) < 2:
        return set(parts)
    first, last = parts[0], parts[-1]
    return {
        first,
        last,
        f"{first}.{last}",
        f"{first}{last}",
        f"{first[0]}{last}",
        f"{first}{last[0]}",
    }


class LocalVerifier:
    def __init__(
        self,
        *,
        resolver: DnsResolver,
        smtp_probe: SMTPProbe,
        domain_limiter: DomainLimiter,
    ) -> None:
        self.resolver = resolver
        self.smtp_probe = smtp_probe
        self.domain_limiter = domain_limiter

    def verify(
        self,
        email: object,
        *,
        contact_name: str = "",
        corporate_domain: str = "",
        history: VerificationHistory | None = None,
    ) -> LocalVerificationResult:
        normalized = _normalize_email(email)
        history = history or VerificationHistory()
        if not EMAIL_RE.fullmatch(normalized):
            evidence = self._evidence("FORMAT", "LOCAL_RULE", "INVALID", "INVALID_FORMAT")
            return self._result(normalized, VerificationStatus.INVALID, 0, 0, [evidence])

        local_part, domain = normalized.rsplit("@", 1)
        reasons: list[str] = []
        evidence: list[VerificationEvidence] = [
            self._evidence("FORMAT", "LOCAL_RULE", "PASS", "FORMAT_VALID")
        ]
        quality = 70
        role_mailbox = local_part in ROLE_LOCAL_PARTS
        disposable = domain in DISPOSABLE_DOMAINS
        if role_mailbox:
            reasons.append("ROLE_MAILBOX")
            quality -= 35
            evidence.append(self._evidence("MAILBOX", "LOCAL_RULE", "RISK", "ROLE_MAILBOX"))
        if disposable:
            reasons.append("DISPOSABLE_DOMAIN")
            quality -= 40
            evidence.append(
                self._evidence("DOMAIN", "BUILTIN_DISPOSABLE_V1", "RISK", "DISPOSABLE_DOMAIN")
            )
        corporate = corporate_domain.strip().lower().rstrip(".")
        if corporate and domain != corporate:
            reasons.append("CORPORATE_DOMAIN_MISMATCH")
            quality -= 20
        if contact_name:
            if local_part in _name_patterns(contact_name):
                reasons.append("NAME_PATTERN_MATCH")
                quality += 15
            elif not role_mailbox:
                reasons.append("NAME_PATTERN_MISMATCH")
                quality -= 15

        try:
            dns_result = self.resolver.resolve(domain)
        except TimeoutError:
            evidence.append(self._evidence("DNS", "DNS", "UNKNOWN", "DNS_TIMEOUT"))
            return self._result(
                normalized,
                VerificationStatus.UNKNOWN,
                25,
                quality,
                evidence,
                reasons + ["DNS_TIMEOUT"],
            )
        if not dns_result.domain_exists:
            evidence.append(self._evidence("DNS", "DNS", "FAIL", "DOMAIN_NOT_FOUND"))
            return self._result(
                normalized, VerificationStatus.INVALID, 0, quality, evidence, reasons + ["DOMAIN_NOT_FOUND"]
            )
        if dns_result.null_mx:
            evidence.append(self._evidence("MX", "DNS", "FAIL", "NULL_MX"))
            return self._result(
                normalized, VerificationStatus.INVALID, 0, quality, evidence, reasons + ["NULL_MX"]
            )
        if not dns_result.mx_hosts:
            evidence.append(self._evidence("MX", "DNS", "FAIL", "NO_MX"))
            return self._result(
                normalized, VerificationStatus.INVALID, 5, quality, evidence, reasons + ["NO_MX"]
            )
        evidence.append(
            self._evidence(
                "MX",
                "DNS",
                "PASS",
                "MX_FOUND",
                {"mx_count": len(dns_result.mx_hosts)},
            )
        )

        if not self.domain_limiter.acquire(domain):
            evidence.append(
                self._evidence("THROTTLE", "SHARED_CACHE", "DEFER", "DOMAIN_RATE_LIMITED")
            )
            return self._result(
                normalized,
                VerificationStatus.UNKNOWN,
                35,
                quality,
                evidence,
                reasons + ["DOMAIN_RATE_LIMITED"],
            )

        smtp = self.smtp_probe.probe(email=normalized, mx_host=dns_result.mx_hosts[0])
        if smtp.disposition == SMTPDisposition.REJECTED:
            smtp_status = VerificationStatus.INVALID
            deliverability = 5
            smtp_reason = "SMTP_RECIPIENT_REJECTED"
        elif smtp.disposition == SMTPDisposition.TIMEOUT:
            smtp_status = VerificationStatus.UNKNOWN
            deliverability = 40
            smtp_reason = "SMTP_TIMEOUT"
        elif smtp.disposition == SMTPDisposition.TEMPORARY:
            smtp_status = VerificationStatus.UNKNOWN
            deliverability = 45
            smtp_reason = "SMTP_GREYLISTED"
        elif smtp.disposition == SMTPDisposition.AMBIGUOUS:
            smtp_status = VerificationStatus.UNKNOWN
            deliverability = 45
            smtp_reason = "SMTP_AMBIGUOUS"
        elif smtp.disposition == SMTPDisposition.BLOCKED:
            smtp_status = VerificationStatus.UNKNOWN
            deliverability = 25
            smtp_reason = "SMTP_TARGET_BLOCKED"
        elif smtp.disposition == SMTPDisposition.ACCEPTED and smtp.catch_all is None:
            smtp_status = VerificationStatus.UNKNOWN
            deliverability = 50
            smtp_reason = "CATCH_ALL_UNKNOWN"
        elif smtp.catch_all is True:
            smtp_status = VerificationStatus.RISKY
            deliverability = 60
            smtp_reason = "CATCH_ALL"
        else:
            smtp_status = VerificationStatus.LIKELY_VALID
            deliverability = 75
            smtp_reason = "SMTP_ACCEPTED_NOT_PROOF"
        evidence.append(
            self._evidence(
                "SMTP",
                "SMTP_RCPT",
                smtp.disposition.value,
                smtp_reason,
                {"response_code": smtp.response_code},
            )
        )
        reasons.append(smtp_reason)

        status = smtp_status
        if history.bounced:
            if status != VerificationStatus.INVALID:
                status = VerificationStatus.RISKY
            deliverability = min(deliverability, 20)
            reasons.append("HISTORICAL_BOUNCE_UNCLASSIFIED")
            evidence.append(
                self._evidence(
                    "HISTORY",
                    "OUTREACH_MESSAGE",
                    "RISK",
                    "HISTORICAL_BOUNCE_UNCLASSIFIED",
                )
            )
        elif history.replied:
            reasons.append("HISTORICAL_REPLY")
            evidence.append(
                self._evidence("HISTORY", "OUTREACH_MESSAGE", "PASS", "HISTORICAL_REPLY")
            )
            if smtp_status != VerificationStatus.INVALID:
                deliverability = max(deliverability, 95)
                status = (
                    VerificationStatus.RISKY
                    if smtp.catch_all is True or disposable
                    else VerificationStatus.VALID
                )
        elif history.sent_count:
            deliverability = min(90, deliverability + 5)
            reasons.append("HISTORICAL_SEND_ACCEPTED")

        if disposable and status not in {VerificationStatus.INVALID, VerificationStatus.UNKNOWN}:
            status = VerificationStatus.RISKY
        return self._result(
            normalized,
            status,
            deliverability,
            quality,
            evidence,
            reasons,
            catch_all=smtp.catch_all,
        )

    @staticmethod
    def _evidence(
        check_type: str,
        source: str,
        outcome: str,
        reason_code: str,
        details: dict | None = None,
    ) -> VerificationEvidence:
        return VerificationEvidence(
            check_type=check_type,
            source=source,
            source_version=VERIFIER_VERSION,
            outcome=outcome,
            reason_code=reason_code,
            details=details or {},
        )

    @staticmethod
    def _result(
        email: str,
        status: VerificationStatus,
        deliverability: int,
        quality: int,
        evidence: list[VerificationEvidence],
        reasons: list[str] | None = None,
        *,
        catch_all: bool | None = None,
    ) -> LocalVerificationResult:
        reason_codes = tuple(dict.fromkeys(reasons or [evidence[-1].reason_code]))
        return LocalVerificationResult(
            email=email,
            status=status,
            deliverability_score=max(0, min(100, deliverability)),
            contact_quality_score=max(0, min(100, quality)),
            reason_codes=reason_codes,
            evidence=tuple(evidence),
            catch_all=catch_all,
        )


def get_local_verifier() -> LocalVerifier:
    return LocalVerifier(
        resolver=SystemDnsResolver(),
        smtp_probe=BasicSMTPProbe(),
        domain_limiter=CacheDomainLimiter(),
    )
