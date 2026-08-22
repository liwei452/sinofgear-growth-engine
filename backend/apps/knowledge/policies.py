from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from django.utils import timezone

from .models import (
    CompanyFact,
    CompanyFactEvidence,
    CompanyKnowledgeProfile,
    KnowledgeEvidence,
    KnowledgeStatus,
)


@dataclass(frozen=True)
class PublicEligibilityBlockingReason:
    code: str
    message: str


@dataclass(frozen=True)
class PublicEligibilityDecision:
    eligible: bool
    blocking_reasons: tuple[PublicEligibilityBlockingReason, ...]


def evaluate_company_fact_public_eligibility(
    fact: CompanyFact,
    *,
    at: datetime | None = None,
    preloaded_bindings: Iterable[CompanyFactEvidence] | None = None,
) -> PublicEligibilityDecision:
    """Return the complete, structured decision for external use of one fact revision."""
    checked_at = at or timezone.now()
    checked_date: date = timezone.localdate(checked_at)
    reasons: list[PublicEligibilityBlockingReason] = []

    profile_is_current_approved = CompanyKnowledgeProfile.objects.filter(
        pk=fact.profile_id,
        organization_id=fact.organization_id,
        status=CompanyKnowledgeProfile.Status.APPROVED,
    ).exists()
    if not profile_is_current_approved:
        reasons.append(
            PublicEligibilityBlockingReason(
                code="PROFILE_NOT_APPROVED",
                message="The fact profile is not the current approved profile for the organization.",
            )
        )

    checks = (
        (
            fact.status == CompanyFact.Status.VERIFIED,
            "FACT_NOT_VERIFIED",
            "The fact revision is not verified.",
        ),
        (
            fact.visibility == CompanyFact.Visibility.PUBLIC,
            "FACT_NOT_PUBLIC",
            "The fact is not marked public.",
        ),
        (
            fact.sensitivity == CompanyFact.Sensitivity.NORMAL,
            "FACT_SENSITIVE",
            "The fact contains sensitive information.",
        ),
        (
            fact.claim_policy == CompanyFact.ClaimPolicy.ALLOW_WITH_EVIDENCE,
            "CLAIM_POLICY_BLOCKED",
            "The fact claim policy does not allow external use.",
        ),
        (not fact.is_demo, "FACT_IS_DEMO", "Demo facts cannot be used externally."),
        (
            fact.valid_from is None or fact.valid_from <= checked_date,
            "FACT_NOT_YET_VALID",
            "The fact is not yet valid.",
        ),
        (
            fact.valid_until is None or fact.valid_until >= checked_date,
            "FACT_EXPIRED",
            "The fact has expired.",
        ),
    )
    for passed, code, message in checks:
        if not passed:
            reasons.append(PublicEligibilityBlockingReason(code=code, message=message))

    bindings = _fact_bindings(fact, preloaded_bindings=preloaded_bindings)
    has_public_support = bool(
        company_fact_public_support_bindings(
            fact,
            at=checked_at,
            preloaded_bindings=bindings,
        )
    )
    if not has_public_support:
        reasons.append(
            PublicEligibilityBlockingReason(
                code="MISSING_PUBLIC_EVIDENCE",
                message="No approved, current, non-demo evidence with public usage rights supports the fact.",
            )
        )

    has_valid_contradiction = any(
        binding.support_type == CompanyFactEvidence.SupportType.CONTRADICTING
        and _binding_matches_fact_scope(fact, binding)
        and _is_valid_contradiction(binding.evidence, checked_at=checked_at)
        for binding in bindings
    )
    if has_valid_contradiction:
        reasons.append(
            PublicEligibilityBlockingReason(
                code="CONTRADICTING_EVIDENCE",
                message="Current approved evidence contradicts the fact.",
            )
        )

    blocking_reasons = tuple(reasons)
    return PublicEligibilityDecision(eligible=not blocking_reasons, blocking_reasons=blocking_reasons)


def company_fact_public_support_bindings(
    fact: CompanyFact,
    *,
    at: datetime | None = None,
    preloaded_bindings: Iterable[CompanyFactEvidence] | None = None,
) -> tuple[CompanyFactEvidence, ...]:
    checked_at = at or timezone.now()
    bindings = _fact_bindings(fact, preloaded_bindings=preloaded_bindings)
    return tuple(
        binding
        for binding in bindings
        if binding.support_type
        in {CompanyFactEvidence.SupportType.PRIMARY, CompanyFactEvidence.SupportType.SUPPORTING}
        and _binding_matches_fact_scope(fact, binding)
        and _evidence_allows_public_use(binding.evidence, checked_at=checked_at)
    )


def _fact_bindings(
    fact: CompanyFact,
    *,
    preloaded_bindings: Iterable[CompanyFactEvidence] | None,
) -> tuple[CompanyFactEvidence, ...]:
    if preloaded_bindings is None:
        return tuple(fact.evidence_bindings.select_related("evidence").all())
    return tuple(preloaded_bindings)


def _binding_matches_fact_scope(
    fact: CompanyFact,
    binding: CompanyFactEvidence,
) -> bool:
    return (
        binding.company_fact_id == fact.id
        and binding.evidence.organization_id == fact.organization_id
    )


def _evidence_allows_public_use(evidence: KnowledgeEvidence, *, checked_at: datetime) -> bool:
    return (
        evidence.status == KnowledgeStatus.APPROVED
        and evidence.usage_rights == KnowledgeEvidence.UsageRights.PUBLIC
        and evidence.sensitivity == KnowledgeEvidence.Sensitivity.NORMAL
        and not evidence.is_demo
        and (evidence.expires_at is None or evidence.expires_at >= checked_at)
    )


def _is_valid_contradiction(evidence: KnowledgeEvidence, *, checked_at: datetime) -> bool:
    return (
        evidence.status == KnowledgeStatus.APPROVED
        and not evidence.is_demo
        and (evidence.expires_at is None or evidence.expires_at >= checked_at)
    )
