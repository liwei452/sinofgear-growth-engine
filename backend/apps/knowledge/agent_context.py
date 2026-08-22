"""Immutable, purpose-scoped consumption of Mission knowledge snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, Mapping

from apps.common.tenancy import tenant_atomic

from .context_builder import KnowledgeContextBuildError, build_mission_context
from .models import KnowledgeContextSnapshot
from .snapshot_models import canonical_json, sha256_text


MAX_AGENT_CONTEXT_BYTES = 32 * 1024
_EXTERNAL_PURPOSES = frozenset(
    {
        "OUTREACH",
        "CONTENT_STRATEGY",
        "MASTER_CONTENT",
        "PLATFORM_VARIANT",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "connectorcredential",
        "connector_credential",
        "credential_reference",
        "provider_response",
        "raw_internal_exception",
        "raw_provider_response",
        "token",
    }
)
_OUTBOUND_TEXT_KEYS = frozenset(
    {
        "body",
        "cta",
        "cta_label",
        "draft",
        "headline",
        "hook",
        "on_screen_text",
        "script",
        "subject",
        "subtitles",
        "title",
        "voiceover",
    }
)
_OUTBOUND_URL_KEYS = frozenset({"cta_url", "landing_page_url"})
_HTTPS_URL_PATTERN = re.compile(r"https://[^\s<>\"']+", re.IGNORECASE)


class AgentContextPurpose(StrEnum):
    LEAD_JUDGMENT = "LEAD_JUDGMENT"
    OUTREACH = "OUTREACH"
    CONTENT_STRATEGY = "CONTENT_STRATEGY"
    MASTER_CONTENT = "MASTER_CONTENT"
    PLATFORM_VARIANT = "PLATFORM_VARIANT"


class KnowledgeContextError(ValueError):
    """A safe structured failure that never embeds source or provider data."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __repr__(self) -> str:
        return f"KnowledgeContextError(code={self.code!r})"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _normalized_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _outbound_strings(value: object) -> tuple[str, ...]:
    strings: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _OUTBOUND_TEXT_KEYS | _OUTBOUND_URL_KEYS and isinstance(
                item, str
            ):
                strings.append(item)
            elif isinstance(item, (Mapping, list, tuple)):
                strings.extend(_outbound_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            strings.extend(_outbound_strings(item))
    return tuple(strings)


def _embedded_https_urls(strings: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        match.group(0).rstrip(".,;:!?)]}")
        for value in strings
        for match in _HTTPS_URL_PATTERN.finditer(value)
    )


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if (
                normalized in _FORBIDDEN_KEYS
                or normalized.endswith("_token")
                or normalized.startswith("token_")
            ):
                return True
            if _has_forbidden_key(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_forbidden_key(item) for item in value)
    return False


def _sorted_rows(rows: object, *keys: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise KnowledgeContextError(
            "KNOWLEDGE_CONTEXT_CORRUPT",
            "Knowledge context contains an invalid collection.",
        )
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: tuple(str(row.get(key, "")) for key in keys),
    )


def _provenance(snapshot: KnowledgeContextSnapshot) -> dict[str, object]:
    return {
        "knowledge_context_snapshot_id": str(snapshot.id),
        "payload_hash": snapshot.payload_hash,
        "schema_version": snapshot.schema_version,
        "builder_version": snapshot.builder_version,
    }


@dataclass(frozen=True, repr=False)
class PurposeAgentContext:
    purpose: AgentContextPurpose
    snapshot_id: object
    organization_id: object
    mission_id: object
    primary_product_id: object
    provenance: Mapping[str, object]
    data: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return _thaw(self.data)

    @property
    def public_fact_ids(self) -> frozenset[str]:
        seller = self.data.get("seller", {})
        claims = seller.get("public_claims", ()) if isinstance(seller, Mapping) else ()
        return frozenset(
            str(claim.get("fact_id"))
            for claim in claims
            if isinstance(claim, Mapping) and claim.get("fact_id")
        )

    @property
    def verified_urls(self) -> frozenset[str]:
        urls: set[str] = set()
        for page in self.data.get("website_pages", ()):
            if not isinstance(page, Mapping):
                continue
            canonical_url = str(page.get("canonical_url") or "").strip()
            if canonical_url:
                urls.add(canonical_url)
            primary_cta = page.get("primary_cta")
            if isinstance(primary_cta, Mapping):
                cta_url = str(primary_cta.get("url") or "").strip()
                if cta_url:
                    urls.add(cta_url)
        return frozenset(urls)

    @property
    def prohibited_claims(self) -> tuple[str, ...]:
        seller = self.data.get("seller", {})
        if not isinstance(seller, Mapping):
            return ()
        return tuple(str(item) for item in seller.get("prohibited_claims", ()))


@dataclass(frozen=True, repr=False)
class AgentContext:
    snapshot_id: object
    organization_id: object
    mission_id: object
    primary_product_id: object
    provenance: Mapping[str, object]
    _payload: Mapping[str, object]

    def for_purpose(self, purpose: AgentContextPurpose | str) -> PurposeAgentContext:
        try:
            resolved = AgentContextPurpose(purpose)
        except ValueError as exc:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_MISMATCH",
                "Unsupported knowledge context purpose.",
            ) from exc

        payload = _thaw(self._payload)
        company = dict(payload["company"])
        public_claims = _sorted_rows(company.pop("public_claims", []), "namespace", "key", "fact_id")
        internal_context = _sorted_rows(
            company.pop("internal_context", []), "namespace", "key", "fact_id"
        )
        company.pop("excluded_summary", None)
        prohibited_claims = sorted(
            {str(item).strip() for item in company.pop("prohibited_claims", []) if str(item).strip()},
            key=str.casefold,
        )
        seller = {
            "company_profile": company,
            "public_claims": public_claims,
            "prohibited_claims": prohibited_claims,
        }
        if resolved in {
            AgentContextPurpose.LEAD_JUDGMENT,
            AgentContextPurpose.CONTENT_STRATEGY,
        }:
            seller["internal_context"] = internal_context
        else:
            # These fields are useful for internal reasoning, but are not
            # publication-safe evidence and must never enter an external prompt.
            company.pop("internal_summary", None)
            company.pop("primary_site_origin", None)

        projection = {
            "purpose": resolved.value,
            "knowledge_provenance": dict(self.provenance),
            "seller": seller,
            "product": dict(payload["product"]),
            "icp_profiles": _sorted_rows(payload["icp_profiles"], "code", "version", "id"),
            "mission": dict(payload["mission"]),
            "website_pages": _sorted_rows(
                payload["website_pages"], "page_type", "language", "canonical_url", "page_id"
            ),
        }
        context = PurposeAgentContext(
            purpose=resolved,
            snapshot_id=self.snapshot_id,
            organization_id=self.organization_id,
            mission_id=self.mission_id,
            primary_product_id=self.primary_product_id,
            provenance=self.provenance,
            data=_freeze(projection),
        )
        has_verified_cta = any(
            isinstance(page, Mapping)
            and isinstance(page.get("primary_cta"), Mapping)
            and str(page["primary_cta"].get("label") or "").strip()
            and str(page["primary_cta"].get("url") or "").strip()
            for page in context.data.get("website_pages", ())
        )
        if resolved.value in _EXTERNAL_PURPOSES and not has_verified_cta:
            raise KnowledgeContextError(
                "VERIFIED_LANDING_PAGE_REQUIRED",
                "A verified landing page and CTA are required for external content.",
            )
        encoded_size = len(canonical_json(context.to_dict()).encode("utf-8"))
        if encoded_size > MAX_AGENT_CONTEXT_BYTES:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_TOO_LARGE",
                "Purpose-scoped knowledge context exceeds the safe size limit.",
            )
        return context


def load_agent_context(*, organization, mission, snapshot_id) -> AgentContext:
    """Load and validate one immutable Mission snapshot under a trusted tenant context."""

    with tenant_atomic(organization.id):
        try:
            snapshot = KnowledgeContextSnapshot.objects.select_related(
                "mission", "primary_product"
            ).get(pk=snapshot_id)
        except KnowledgeContextSnapshot.DoesNotExist as exc:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_REQUIRED",
                "Knowledge context snapshot is required.",
            ) from exc

        if (
            snapshot.organization_id != organization.id
            or snapshot.mission_id != mission.id
            or mission.organization_id != organization.id
            or snapshot.primary_product_id != mission.primary_product_id
        ):
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_MISMATCH",
                "Knowledge context does not match the requested Mission.",
            )
        if snapshot.schema_version != KnowledgeContextSnapshot.SCHEMA_VERSION:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_MISMATCH",
                "Knowledge context schema version is not supported.",
            )
        payload = snapshot.payload
        if not isinstance(payload, dict) or _has_forbidden_key(payload):
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_CORRUPT",
                "Knowledge context payload is invalid.",
            )
        canonical_payload = canonical_json(payload)
        payload_size = len(canonical_payload.encode("utf-8"))
        if (
            sha256_text(canonical_payload) != snapshot.payload_hash
            or payload_size != snapshot.payload_size_bytes
            or payload.get("schema_version") != snapshot.schema_version
            or payload.get("builder_version") != snapshot.builder_version
            or str(payload.get("mission", {}).get("id")) != str(mission.id)
            or str(payload.get("product", {}).get("id")) != str(mission.primary_product_id)
        ):
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_CORRUPT",
                "Knowledge context payload integrity validation failed.",
            )
        if payload_size > 512 * 1024:
            raise KnowledgeContextError(
                "KNOWLEDGE_CONTEXT_TOO_LARGE",
                "Knowledge context payload exceeds the safe size limit.",
            )
        provenance = _freeze(_provenance(snapshot))
        return AgentContext(
            snapshot_id=snapshot.id,
            organization_id=snapshot.organization_id,
            mission_id=snapshot.mission_id,
            primary_product_id=snapshot.primary_product_id,
            provenance=provenance,
            _payload=_freeze(payload),
        )


def load_or_build_agent_context(
    *, organization, mission, actor=None, snapshot_id=None
) -> AgentContext:
    """Use the supplied snapshot, or freeze current Mission knowledge exactly once."""

    if snapshot_id is None:
        try:
            snapshot = build_mission_context(
                organization=organization,
                mission=mission,
                actor=actor,
            )
        except KnowledgeContextBuildError as exc:
            code = (
                "KNOWLEDGE_CONTEXT_TOO_LARGE"
                if exc.code == "CONTEXT_TOO_LARGE"
                else "KNOWLEDGE_CONTEXT_REQUIRED"
            )
            raise KnowledgeContextError(code, "Required Mission knowledge is unavailable.") from exc
        snapshot_id = snapshot.id
    return load_agent_context(
        organization=organization,
        mission=mission,
        snapshot_id=snapshot_id,
    )


def validate_external_output(
    output: Mapping[str, object], *, context: PurposeAgentContext
) -> Mapping[str, object]:
    """Fail closed on invalid citations, landing pages, or prohibited statements."""

    if context.purpose == AgentContextPurpose.LEAD_JUDGMENT:
        raise KnowledgeContextError(
            "PUBLIC_CLAIM_BLOCKED",
            "Lead-judgment context is not an external publication context.",
        )
    cited_ids = output.get("cited_fact_ids", [])
    if not isinstance(cited_ids, (list, tuple)) or not cited_ids or any(
        str(item) not in context.public_fact_ids for item in cited_ids
    ):
        raise KnowledgeContextError(
            "PUBLIC_CLAIM_BLOCKED",
            "External output cites a fact that is not publicly eligible.",
        )
    outward_strings = _outbound_strings(output)
    supplied_urls = _embedded_https_urls(outward_strings)
    if any(url not in context.verified_urls for url in supplied_urls):
        raise KnowledgeContextError(
            "VERIFIED_LANDING_PAGE_REQUIRED",
            "External output uses an unverified landing page.",
        )
    text = _normalized_text("\n".join(outward_strings))
    if any(
        normalized and normalized in text
        for normalized in map(_normalized_text, context.prohibited_claims)
    ):
        raise KnowledgeContextError(
            "PUBLIC_CLAIM_BLOCKED",
            "External output contains a prohibited claim.",
        )
    return output
