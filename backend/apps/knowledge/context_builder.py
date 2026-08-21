from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import Product
from apps.growth.models import GrowthMission, MissionPlan

from .context_models import normalize_https_url, normalize_optional_cta_url
from .models import (
    CompanyFact,
    CompanyFactEvidence,
    CompanyKnowledgeProfile,
    ICPProductLink,
    ICPProfile,
    KnowledgeContextSnapshot,
    KnowledgeEvidence,
    KnowledgeStatus,
    WebsitePage,
    WebsitePageConceptLink,
    WebsitePageProductLink,
)
from .policies import evaluate_company_fact_public_eligibility
from .product_context import CatalogProductContextAdapter
from .snapshot_models import canonical_json, sha256_text


BUILDER_VERSION = "mission-context-builder-v1"
MAX_PUBLIC_CLAIMS = 200
MAX_INTERNAL_CONTEXT = 100
MAX_WEBSITE_PAGES = 50
MAX_ICP_PROFILES = 10
MAX_EVIDENCE_EXCERPT_CHARS = 2000
MAX_PAYLOAD_BYTES = 512 * 1024
COMPANY_PAGE_TYPES = frozenset(
    {
        WebsitePage.PageType.HOME,
        WebsitePage.PageType.ABOUT,
        WebsitePage.PageType.CAPABILITY,
        WebsitePage.PageType.CONTACT,
        WebsitePage.PageType.RFQ,
    }
)


class KnowledgeContextBuildError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _fixed(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, list):
        return [_fixed(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _fixed(item) for key, item in value.items()}
    return value


def _source_hash(value: object) -> str:
    return sha256_text(canonical_json(_fixed(value)))


def _valid_date_window(fact: CompanyFact, today: date) -> bool:
    return (fact.valid_from is None or fact.valid_from <= today) and (
        fact.valid_until is None or fact.valid_until >= today
    )


def _truncate(items: list, limit: int, *, section: str, truncation: dict) -> list:
    if len(items) > limit:
        truncation[section] = {
            "limit": limit,
            "omitted_count": len(items) - limit,
        }
    return items[:limit]


def _summary(counter: Counter, *, total: int | None = None) -> dict:
    return {
        "total": sum(counter.values()) if total is None else total,
        "by_reason": {key: counter[key] for key in sorted(counter)},
    }


def _forbidden_context_key(value: object) -> str | None:
    forbidden = {
        "api_key",
        "apikey",
        "authorization",
        "connectorcredential",
        "connector_credential",
        "credential_reference",
        "provider_response",
        "raw_provider_response",
        "token",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if (
                normalized in forbidden
                or normalized.endswith("_token")
                or normalized.startswith("token_")
            ):
                return str(key)
            nested = _forbidden_context_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _forbidden_context_key(item)
            if nested:
                return nested
    return None


@dataclass
class _FactBuildResult:
    public_claims: list[dict]
    internal_context: list[dict]
    excluded_summary: dict
    source_entries: list[dict]
    excerpt_truncated_count: int


@dataclass
class _PageBuildResult:
    pages: list[dict]
    excluded_summary: dict
    source_entries: list[dict]


class KnowledgeContextBuilder:
    def __init__(self, *, product_adapter: CatalogProductContextAdapter | None = None) -> None:
        self.product_adapter = product_adapter or CatalogProductContextAdapter()

    @transaction.atomic
    def build_mission_context(
        self,
        *,
        organization,
        mission,
        actor=None,
        icp_profile_ids=None,
    ) -> KnowledgeContextSnapshot:
        locked_mission = self._mission(organization, mission)
        product = self._product(organization, locked_mission)
        profile = self._company_profile(organization)
        plan = self._mission_plan(organization, locked_mission)
        icps, icp_links = self._icps(
            organization,
            product,
            icp_profile_ids=icp_profile_ids,
        )
        now = timezone.now()
        truncation: dict[str, dict] = {}
        fact_result = self._facts(profile, at=now, truncation=truncation)
        page_result = self._pages(organization, product, truncation=truncation)
        product_payload = self.product_adapter.serialize(product)
        all_icp_payload = self._serialize_icps(icps, icp_links)
        icp_payload = _truncate(
            all_icp_payload,
            MAX_ICP_PROFILES,
            section="icp_profiles",
            truncation=truncation,
        )
        mission_payload = self._serialize_mission(locked_mission, plan)
        company_payload = self._serialize_profile(profile)
        company_payload.update(
            {
                "public_claims": fact_result.public_claims,
                "internal_context": fact_result.internal_context,
                "excluded_summary": fact_result.excluded_summary,
            }
        )
        if fact_result.excerpt_truncated_count:
            truncation["evidence_excerpts"] = {
                "limit": MAX_EVIDENCE_EXCERPT_CHARS,
                "omitted_count": fact_result.excerpt_truncated_count,
            }
        payload = {
            "schema_version": KnowledgeContextSnapshot.SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "mission": mission_payload,
            "company": company_payload,
            "product": product_payload,
            "icp_profiles": icp_payload,
            "website_pages": page_result.pages,
            "website_excluded_summary": page_result.excluded_summary,
            "truncation": truncation,
        }
        forbidden_key = _forbidden_context_key(payload)
        if forbidden_key:
            raise KnowledgeContextBuildError(
                "UNSAFE_CONTEXT_SOURCE",
                "A context source contains a forbidden credential or provider-response field.",
                details={"field": forbidden_key},
            )
        canonical_payload = canonical_json(payload)
        payload_size = len(canonical_payload.encode("utf-8"))
        if payload_size > MAX_PAYLOAD_BYTES:
            raise KnowledgeContextBuildError(
                "CONTEXT_TOO_LARGE",
                "Canonical mission knowledge context exceeds 512 KiB.",
                details={"payload_size_bytes": payload_size, "limit_bytes": MAX_PAYLOAD_BYTES},
            )
        payload_hash = sha256_text(canonical_payload)
        source_fingerprint = self._fingerprint(
            mission=locked_mission,
            mission_payload=mission_payload,
            plan=plan,
            profile=profile,
            company_payload=company_payload,
            product=product,
            product_payload=product_payload,
            icps=icps,
            icp_payload=all_icp_payload,
            fact_entries=fact_result.source_entries,
            page_entries=page_result.source_entries,
        )
        lookup = {
            "organization": organization,
            "scope": KnowledgeContextSnapshot.Scope.MISSION,
            "source_fingerprint": source_fingerprint,
        }
        existing = KnowledgeContextSnapshot.objects.filter(**lookup).first()
        if existing:
            return existing
        values = {
            **lookup,
            "mission": locked_mission,
            "mission_plan": plan,
            "schema_version": KnowledgeContextSnapshot.SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "company_profile": profile,
            "primary_product": product,
            "payload_hash": payload_hash,
            "payload": payload,
            "payload_size_bytes": payload_size,
            "created_by": actor,
        }
        try:
            with transaction.atomic():
                return KnowledgeContextSnapshot.objects.create(**values)
        except IntegrityError:
            return KnowledgeContextSnapshot.objects.get(**lookup)

    @staticmethod
    def _mission(organization, mission) -> GrowthMission:
        if not isinstance(mission, GrowthMission) or not mission.pk:
            raise KnowledgeContextBuildError("INVALID_MISSION", "A persisted GrowthMission is required.")
        locked = GrowthMission.objects.select_for_update().filter(pk=mission.pk).first()
        if not locked or locked.organization_id != organization.id:
            raise KnowledgeContextBuildError(
                "ORGANIZATION_MISMATCH",
                "Mission must belong to the requested organization.",
            )
        return locked

    @staticmethod
    def _product(organization, mission: GrowthMission) -> Product:
        product = (
            Product.objects.select_for_update()
            .filter(pk=mission.primary_product_id)
            .first()
        )
        if not product or product.organization_id != organization.id:
            raise KnowledgeContextBuildError(
                "ORGANIZATION_MISMATCH",
                "Mission primary product must belong to the requested organization.",
            )
        if product.status != Product.Status.ACTIVE:
            raise KnowledgeContextBuildError(
                "PRIMARY_PRODUCT_INACTIVE",
                "Mission primary product must remain ACTIVE.",
            )
        return product

    @staticmethod
    def _company_profile(organization) -> CompanyKnowledgeProfile:
        profile = (
            CompanyKnowledgeProfile.objects.select_for_update()
            .filter(
                organization=organization,
                status=CompanyKnowledgeProfile.Status.APPROVED,
            )
            .order_by("-version", "id")
            .first()
        )
        if not profile:
            raise KnowledgeContextBuildError(
                "COMPANY_PROFILE_REQUIRED",
                "A current approved company knowledge profile is required.",
            )
        return profile

    @staticmethod
    def _mission_plan(organization, mission: GrowthMission) -> MissionPlan | None:
        plan = (
            MissionPlan.objects.select_for_update()
            .filter(mission=mission, status=MissionPlan.Status.APPROVED)
            .order_by("-version", "id")
            .first()
        )
        if plan and (plan.organization_id != organization.id or plan.mission_id != mission.id):
            raise KnowledgeContextBuildError(
                "ORGANIZATION_MISMATCH",
                "Mission plan must belong to the requested organization and mission.",
            )
        return plan

    @staticmethod
    def _icps(organization, product: Product, *, icp_profile_ids):
        explicit = icp_profile_ids is not None
        if explicit:
            if (
                type(icp_profile_ids) is not list
                or any(type(item) is not UUID for item in icp_profile_ids)
                or len(set(icp_profile_ids)) != len(icp_profile_ids)
                or not icp_profile_ids
            ):
                raise KnowledgeContextBuildError(
                    "INVALID_ICP_SELECTION",
                    "Explicit ICP selection must be a non-empty, unique list of native UUID values.",
                )
            profiles = list(
                ICPProfile.objects.select_for_update()
                .filter(pk__in=icp_profile_ids)
                .order_by("code", "version", "id")
            )
            if len(profiles) != len(icp_profile_ids):
                raise KnowledgeContextBuildError(
                    "INVALID_ICP_SELECTION",
                    "Every explicitly selected ICP must exist.",
                )
        else:
            profiles = list(
                ICPProfile.objects.select_for_update()
                .filter(
                    organization=organization,
                    status=ICPProfile.Status.APPROVED,
                    product_links__product=product,
                )
                .distinct()
                .order_by("code", "version", "id")
            )
            if not profiles:
                raise KnowledgeContextBuildError(
                    "ICP_CONFIGURATION_REQUIRED",
                    "No approved ICP is configured for the mission primary product.",
                )
            if len(profiles) > 1:
                raise KnowledgeContextBuildError(
                    "ICP_SELECTION_REQUIRED",
                    "Multiple approved ICPs match; explicit selection is required.",
                )
        profile_ids = [profile.id for profile in profiles]
        links = list(
            ICPProductLink.objects.select_for_update()
            .filter(icp_profile_id__in=profile_ids)
            .select_related("product")
            .order_by("icp_profile__code", "icp_profile__version", "id")
        )
        links_by_profile = defaultdict(list)
        for link in links:
            links_by_profile[link.icp_profile_id].append(link)
        invalid = False
        for profile in profiles:
            matching_primary = False
            if (
                profile.organization_id != organization.id
                or profile.status != ICPProfile.Status.APPROVED
            ):
                invalid = True
            for link in links_by_profile[profile.id]:
                if (
                    link.product.organization_id != organization.id
                    or link.product.status != Product.Status.ACTIVE
                ):
                    invalid = True
                if link.product_id == product.id:
                    matching_primary = True
            if not matching_primary:
                invalid = True
        if invalid:
            code = "INVALID_ICP_SELECTION" if explicit else "ICP_CONFIGURATION_REQUIRED"
            raise KnowledgeContextBuildError(
                code,
                "Selected ICPs must be current, organization-owned, and linked to the ACTIVE primary product.",
            )
        return profiles, links_by_profile

    @staticmethod
    def _serialize_icps(icps, links_by_profile) -> list[dict]:
        output = []
        for profile in icps:
            output.append(
                {
                    "id": str(profile.id),
                    "code": profile.code,
                    "version": profile.version,
                    "status": profile.status,
                    "name": profile.name,
                    "description": profile.description,
                    "target_industries": list(profile.target_industries),
                    "company_types": list(profile.company_types),
                    "buyer_roles": list(profile.buyer_roles),
                    "target_markets": list(profile.target_markets),
                    "languages": list(profile.languages),
                    "pain_points": list(profile.pain_points),
                    "buying_triggers": list(profile.buying_triggers),
                    "exclusion_rules": list(profile.exclusion_rules),
                    "preferred_channels": list(profile.preferred_channels),
                    "product_links": [
                        {
                            "link_id": str(link.id),
                            "product_id": str(link.product_id),
                            "product_version": link.product.version,
                            "product_status": link.product.status,
                            "role": link.role,
                            "priority": link.priority,
                            "use_cases": list(link.use_cases),
                        }
                        for link in links_by_profile[profile.id]
                    ],
                }
            )
        return output

    @staticmethod
    def _facts(profile, *, at: datetime, truncation: dict) -> _FactBuildResult:
        today = timezone.localdate(at)
        facts = list(
            CompanyFact.objects.select_for_update()
            .filter(profile=profile, status=CompanyFact.Status.VERIFIED)
            .prefetch_related("evidence_bindings__evidence")
            .order_by("namespace", "key", "version", "id")
        )
        public_claims = []
        internal_context = []
        excluded = Counter()
        excluded_total = 0
        source_entries = []
        excerpt_truncated_count = 0
        for fact in facts:
            bindings = sorted(
                fact.evidence_bindings.all(),
                key=lambda item: (item.support_type, str(item.evidence_id), str(item.id)),
            )
            source_entries.append(
                {
                    "id": str(fact.id),
                    "version": fact.version,
                    "status": fact.status,
                    "hash": _source_hash(
                        {
                            "value": fact.value_json,
                            "visibility": fact.visibility,
                            "sensitivity": fact.sensitivity,
                            "claim_policy": fact.claim_policy,
                            "risk_level": fact.risk_level,
                            "valid_from": fact.valid_from,
                            "valid_until": fact.valid_until,
                            "is_demo": fact.is_demo,
                            "evidence": [
                                {
                                    "id": binding.evidence_id,
                                    "support_type": binding.support_type,
                                    "status": binding.evidence.status,
                                    "version": binding.evidence.version,
                                    "content_hash": binding.evidence.content_hash,
                                    "source_hash": _source_hash(
                                        {
                                            "source_url": binding.evidence.source_url,
                                            "excerpt": binding.evidence.excerpt,
                                            "captured_at": binding.evidence.captured_at,
                                            "usage_rights": binding.evidence.usage_rights,
                                            "sensitivity": binding.evidence.sensitivity,
                                            "is_demo": binding.evidence.is_demo,
                                            "expires_at": binding.evidence.expires_at,
                                        }
                                    ),
                                }
                                for binding in bindings
                            ],
                        }
                    ),
                }
            )
            hard_reasons = []
            if fact.organization_id != profile.organization_id:
                hard_reasons.append("FACT_ORGANIZATION_MISMATCH")
            if fact.claim_policy == CompanyFact.ClaimPolicy.NEVER_SEND_TO_MODEL:
                hard_reasons.append("NEVER_SEND_TO_MODEL")
            if fact.sensitivity == CompanyFact.Sensitivity.CONFIDENTIAL:
                hard_reasons.append("CONFIDENTIAL")
            if fact.sensitivity == CompanyFact.Sensitivity.SECRET:
                hard_reasons.append("SECRET")
            if fact.is_demo:
                hard_reasons.append("FACT_IS_DEMO")
            if fact.valid_from and fact.valid_from > today:
                hard_reasons.append("FACT_NOT_YET_VALID")
            if fact.valid_until and fact.valid_until < today:
                hard_reasons.append("FACT_EXPIRED")
            if hard_reasons:
                excluded.update(set(hard_reasons))
                excluded_total += 1
                source_entries[-1]["classification"] = {
                    "section": "excluded",
                    "reasons": sorted(set(hard_reasons)),
                }
                continue
            if fact.claim_policy == CompanyFact.ClaimPolicy.INTERNAL_CONTEXT_ONLY:
                if fact.sensitivity == CompanyFact.Sensitivity.NORMAL and _valid_date_window(
                    fact, today
                ):
                    internal_context.append(
                        {
                            "fact_id": str(fact.id),
                            "namespace": fact.namespace,
                            "key": fact.key,
                            "version": fact.version,
                            "value": fact.value_json,
                            "valid_from": _fixed(fact.valid_from),
                            "valid_until": _fixed(fact.valid_until),
                            "external_use_allowed": False,
                        }
                    )
                    source_entries[-1]["classification"] = {"section": "internal_context"}
                else:
                    excluded["INTERNAL_CONTEXT_BLOCKED"] += 1
                    excluded_total += 1
                    source_entries[-1]["classification"] = {
                        "section": "excluded",
                        "reasons": ["INTERNAL_CONTEXT_BLOCKED"],
                    }
                continue
            decision = evaluate_company_fact_public_eligibility(fact, at=at)
            if not decision.eligible:
                blocking_codes = {reason.code for reason in decision.blocking_reasons}
                excluded.update(blocking_codes)
                excluded_total += 1
                source_entries[-1]["classification"] = {
                    "section": "excluded",
                    "reasons": sorted(blocking_codes),
                }
                continue
            citations = []
            for binding in bindings:
                evidence = binding.evidence
                if (
                    binding.support_type
                    not in {
                        CompanyFactEvidence.SupportType.PRIMARY,
                        CompanyFactEvidence.SupportType.SUPPORTING,
                    }
                    or evidence.status != KnowledgeStatus.APPROVED
                    or evidence.organization_id != fact.organization_id
                    or evidence.usage_rights != KnowledgeEvidence.UsageRights.PUBLIC
                    or evidence.sensitivity != KnowledgeEvidence.Sensitivity.NORMAL
                    or evidence.is_demo
                    or (evidence.expires_at and evidence.expires_at < at)
                ):
                    continue
                excerpt = evidence.excerpt[:MAX_EVIDENCE_EXCERPT_CHARS]
                if len(evidence.excerpt) > MAX_EVIDENCE_EXCERPT_CHARS:
                    excerpt_truncated_count += 1
                citations.append(
                    {
                        "evidence_id": str(evidence.id),
                        "evidence_type": evidence.evidence_type,
                        "source_url": evidence.source_url,
                        "excerpt": excerpt,
                        "content_hash": evidence.content_hash,
                        "captured_at": _fixed(evidence.captured_at),
                    }
                )
            if not citations:
                excluded["MISSING_PUBLIC_EVIDENCE"] += 1
                excluded_total += 1
                source_entries[-1]["classification"] = {
                    "section": "excluded",
                    "reasons": ["MISSING_PUBLIC_EVIDENCE"],
                }
                continue
            public_claims.append(
                {
                    "fact_id": str(fact.id),
                    "namespace": fact.namespace,
                    "key": fact.key,
                    "version": fact.version,
                    "value": fact.value_json,
                    "risk_level": fact.risk_level,
                    "valid_from": _fixed(fact.valid_from),
                    "valid_until": _fixed(fact.valid_until),
                    "evidence": citations,
                }
            )
            source_entries[-1]["classification"] = {"section": "public_claims"}
        public_claims = _truncate(
            public_claims,
            MAX_PUBLIC_CLAIMS,
            section="public_claims",
            truncation=truncation,
        )
        internal_context = _truncate(
            internal_context,
            MAX_INTERNAL_CONTEXT,
            section="internal_context",
            truncation=truncation,
        )
        return _FactBuildResult(
            public_claims=public_claims,
            internal_context=internal_context,
            excluded_summary=_summary(excluded, total=excluded_total),
            source_entries=source_entries,
            excerpt_truncated_count=excerpt_truncated_count,
        )

    @staticmethod
    def _pages(organization, product: Product, *, truncation: dict) -> _PageBuildResult:
        pages = list(
            WebsitePage.objects.select_for_update()
            .filter(organization=organization, status=WebsitePage.Status.VERIFIED, is_demo=False)
            .filter(Q(page_type__in=COMPANY_PAGE_TYPES) | Q(product_links__product=product))
            .distinct()
            .order_by("canonical_url", "version", "id")
        )
        page_ids = [page.id for page in pages]
        product_links = list(
            WebsitePageProductLink.objects.select_for_update()
            .filter(website_page_id__in=page_ids)
            .select_related("product")
            .order_by("website_page_id", "id")
        )
        concept_links = list(
            WebsitePageConceptLink.objects.select_for_update()
            .filter(website_page_id__in=page_ids)
            .select_related("concept")
            .order_by("website_page_id", "role", "id")
        )
        products_by_page = defaultdict(list)
        concepts_by_page = defaultdict(list)
        for link in product_links:
            products_by_page[link.website_page_id].append(link)
        for link in concept_links:
            concepts_by_page[link.website_page_id].append(link)
        usable = []
        excluded = Counter()
        excluded_total = 0
        source_entries = []
        compatible = {
            WebsitePageConceptLink.Role.INDUSTRY: "INDUSTRY",
            WebsitePageConceptLink.Role.APPLICATION: "APPLICATION",
            WebsitePageConceptLink.Role.PURCHASE_INTENT: "PURCHASE_INTENT",
        }
        for page in pages:
            reasons = set()
            try:
                canonical_url = normalize_https_url(page.canonical_url)
            except ValidationError:
                reasons.add("INVALID_CANONICAL_URL")
                canonical_url = None
            try:
                cta_url = normalize_optional_cta_url(page.primary_cta_url)
            except ValidationError:
                reasons.add("INVALID_CTA_URL")
                cta_url = None
            product_provenance = []
            for link in products_by_page[page.id]:
                linked_product = link.product
                if linked_product.organization_id != organization.id:
                    reasons.add("PRODUCT_ORGANIZATION_MISMATCH")
                if linked_product.status != Product.Status.ACTIVE:
                    reasons.add("PRODUCT_NOT_ACTIVE")
                product_provenance.append(
                    {
                        "link_id": str(link.id),
                        "product_id": str(link.product_id),
                        "product_version": linked_product.version,
                        "product_status": linked_product.status,
                        "relation_type": link.relation_type,
                    }
                )
            concept_provenance = []
            for link in concepts_by_page[page.id]:
                concept = link.concept
                if concept.status != KnowledgeStatus.APPROVED:
                    reasons.add("CONCEPT_NOT_APPROVED")
                if concept.organization_id not in {None, organization.id}:
                    reasons.add("CONCEPT_ORGANIZATION_MISMATCH")
                if compatible.get(link.role) != concept.concept_type:
                    reasons.add("CONCEPT_ROLE_TYPE_MISMATCH")
                concept_provenance.append(
                    {
                        "link_id": str(link.id),
                        "concept_id": str(link.concept_id),
                        "concept_version": concept.version,
                        "concept_status": concept.status,
                        "concept_scope": concept.scope,
                        "concept_type": concept.concept_type,
                        "role": link.role,
                    }
                )
            page_source = {
                "id": str(page.id),
                "version": page.version,
                "status": page.status,
                "content_hash": page.content_hash,
                "hash": _source_hash(
                    {
                        "canonical_url": page.canonical_url,
                        "page_type": page.page_type,
                        "language": page.language,
                        "title": page.title,
                        "content_summary": page.content_summary,
                        "primary_cta_label": page.primary_cta_label,
                        "primary_cta_url": page.primary_cta_url,
                        "seo_keywords": page.seo_keywords,
                        "source_type": page.source_type,
                        "last_verified_at": page.last_verified_at,
                        "is_demo": page.is_demo,
                        "products": product_provenance,
                        "concepts": concept_provenance,
                        "reasons": sorted(reasons),
                    }
                ),
            }
            source_entries.append(page_source)
            if reasons:
                excluded.update(reasons)
                excluded_total += 1
                continue
            usable.append(
                {
                    "page_id": str(page.id),
                    "version": page.version,
                    "canonical_url": canonical_url,
                    "page_type": page.page_type,
                    "language": page.language,
                    "title": page.title,
                    "content_summary": page.content_summary,
                    "primary_cta": {
                        "label": page.primary_cta_label,
                        "url": cta_url,
                    },
                    "seo_keywords": list(page.seo_keywords),
                    "content_hash": page.content_hash,
                    "source_type": page.source_type,
                    "last_verified_at": _fixed(page.last_verified_at),
                    "products": product_provenance,
                    "concepts": concept_provenance,
                }
            )
        usable = _truncate(
            usable,
            MAX_WEBSITE_PAGES,
            section="website_pages",
            truncation=truncation,
        )
        return _PageBuildResult(
            pages=usable,
            excluded_summary=_summary(excluded, total=excluded_total),
            source_entries=source_entries,
        )

    @staticmethod
    def _serialize_mission(mission: GrowthMission, plan: MissionPlan | None) -> dict:
        return {
            "id": str(mission.id),
            "title": mission.title,
            "objective": mission.objective,
            "target_countries": list(mission.target_countries),
            "target_industries": list(mission.target_industries),
            "customer_profile": mission.customer_profile,
            "allowed_channels": list(mission.allowed_channels),
            "start_date": mission.start_date.isoformat(),
            "end_date": mission.end_date.isoformat(),
            "target_account_count": mission.target_account_count,
            "target_reply_count": mission.target_reply_count,
            "target_rfq_count": mission.target_rfq_count,
            "budget_micros": mission.budget_micros,
            "attribution_code": mission.attribution_code,
            "plan": (
                {
                    "id": str(plan.id),
                    "version": plan.version,
                    "status": plan.status,
                }
                if plan
                else None
            ),
        }

    @staticmethod
    def _serialize_profile(profile: CompanyKnowledgeProfile) -> dict:
        return {
            "profile_id": str(profile.id),
            "version": profile.version,
            "status": profile.status,
            "brand_name": profile.brand_name,
            "legal_name_zh": profile.legal_name_zh,
            "legal_name_en": profile.legal_name_en,
            "brand_aliases": list(profile.brand_aliases),
            "internal_summary": profile.internal_summary,
            "default_language": profile.default_language,
            "supported_languages": list(profile.supported_languages),
            "primary_site_origin": profile.primary_site_origin,
            "disclosure_rules": dict(profile.disclosure_rules),
            "prohibited_claims": list(profile.prohibited_claims),
        }

    @staticmethod
    def _fingerprint(
        *,
        mission,
        mission_payload,
        plan,
        profile,
        company_payload,
        product,
        product_payload,
        icps,
        icp_payload,
        fact_entries,
        page_entries,
    ) -> str:
        manifest = {
            "schema_version": KnowledgeContextSnapshot.SCHEMA_VERSION,
            "builder_version": BUILDER_VERSION,
            "limits": {
                "public_claims": MAX_PUBLIC_CLAIMS,
                "internal_context": MAX_INTERNAL_CONTEXT,
                "website_pages": MAX_WEBSITE_PAGES,
                "icp_profiles": MAX_ICP_PROFILES,
                "evidence_excerpt_chars": MAX_EVIDENCE_EXCERPT_CHARS,
                "payload_bytes": MAX_PAYLOAD_BYTES,
            },
            "mission": {
                "id": str(mission.id),
                "status": mission.status,
                "hash": _source_hash(mission_payload),
            },
            "mission_plan": (
                {
                    "id": str(plan.id),
                    "version": plan.version,
                    "status": plan.status,
                    "hash": _source_hash(plan.snapshot),
                }
                if plan
                else None
            ),
            "company_profile": {
                "id": str(profile.id),
                "version": profile.version,
                "status": profile.status,
                "hash": _source_hash(company_payload),
            },
            "product": {
                "id": str(product.id),
                "version": product.version,
                "status": product.status,
                "hash": _source_hash(product_payload),
            },
            "icps": [
                {
                    "id": str(profile.id),
                    "version": profile.version,
                    "status": profile.status,
                    "hash": _source_hash(payload),
                }
                for profile, payload in zip(icps, icp_payload, strict=False)
            ],
            "facts": fact_entries,
            "website_pages": page_entries,
        }
        return _source_hash(manifest)


def build_mission_context(
    *,
    organization,
    mission,
    actor=None,
    icp_profile_ids=None,
) -> KnowledgeContextSnapshot:
    return KnowledgeContextBuilder().build_mission_context(
        organization=organization,
        mission=mission,
        actor=actor,
        icp_profile_ids=icp_profile_ids,
    )
