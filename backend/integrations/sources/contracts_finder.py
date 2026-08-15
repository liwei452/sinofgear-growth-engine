import html
from datetime import datetime, time, timezone
from uuid import UUID

from .base import DiscoveryQuery, SourceAdapterError, SourceBatch, SourceItem
from .ted import JsonTransport, UrllibJsonTransport


CONTRACTS_FINDER_SEARCH_URL = (
    "https://www.contractsfinder.service.gov.uk/api/rest/2/search_notices/json"
)
CONTRACTS_FINDER_NOTICE_ROOT = (
    "https://www.contractsfinder.service.gov.uk/Published/Notice/releases/"
)
CONTRACTS_FINDER_PUBLIC_ROOT = "https://www.contractsfinder.service.gov.uk/Notice/"
CONTRACTS_FINDER_TIMEOUT_SECONDS = 15
CONTRACTS_FINDER_MAX_RESPONSE_BYTES = 2_000_000


class ContractsFinderSource:
    source_code = "UK_CONTRACTS_FINDER"

    def __init__(
        self,
        *,
        transport: JsonTransport | None = None,
        timeout_seconds: int = CONTRACTS_FINDER_TIMEOUT_SECONDS,
        max_response_bytes: int = CONTRACTS_FINDER_MAX_RESPONSE_BYTES,
    ):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Contracts Finder timeout must be between 1 and 30 seconds.")
        if not 100_000 <= max_response_bytes <= CONTRACTS_FINDER_MAX_RESPONSE_BYTES:
            raise ValueError(
                "Contracts Finder response limit must be between 100000 and 2000000 bytes."
            )
        self.transport = transport or UrllibJsonTransport()
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def fetch(self, query: DiscoveryQuery) -> SourceBatch:
        response = self.transport.post_json(
            url=CONTRACTS_FINDER_SEARCH_URL,
            payload={
                "searchCriteria": {
                    "statuses": ["Open"],
                    "cpvCodes": list(query.cpv_codes),
                    "publishedFrom": f"{query.published_from.isoformat()}T00:00:00Z",
                },
                "size": query.limit,
            },
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        hits = response.get("noticeList", [])
        if not isinstance(hits, list):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        items = []
        skipped_count = 0
        for hit in hits[: query.limit]:
            item = self._normalize_hit(hit, query)
            if item is None:
                skipped_count += 1
            else:
                items.append(item)
        return SourceBatch(
            items=tuple(items),
            capability_snapshot={
                "source": "UK_CONTRACTS_FINDER",
                "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS",
                "result_limit": query.limit,
            },
            skipped_count=skipped_count,
            total_count=int(response.get("hitCount") or len(hits)),
        )

    def _normalize_hit(self, hit, query) -> SourceItem | None:
        if not isinstance(hit, dict) or not isinstance(hit.get("item"), dict):
            return None
        notice = hit["item"]
        external_id = _canonical_uuid(notice.get("id"))
        buyer_name = _plain_text(notice.get("organisationName"))
        title = _plain_text(notice.get("title"))
        published_at = _iso_datetime(notice.get("publishedDate"))
        cpv_codes = _cpv_codes(notice.get("cpvCodes"))
        if not set(cpv_codes).intersection(query.cpv_codes):
            return None
        if not all((external_id, buyer_name, title, published_at)):
            return None
        source_url = f"{CONTRACTS_FINDER_PUBLIC_ROOT}{external_id}"
        detail = self.transport.get_json(
            url=f"{CONTRACTS_FINDER_NOTICE_ROOT}{external_id}.json",
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        buyer_identifier = _buyer_identifier(detail)
        return SourceItem(
            source_code="UK_CONTRACTS_FINDER",
            external_id=external_id,
            buyer_name=buyer_name,
            buyer_country="GBR",
            title=title,
            published_at=published_at,
            deadline_at=_iso_datetime(notice.get("deadlineDate")),
            source_url=source_url,
            cpv_codes=cpv_codes,
            buyer_identifier=buyer_identifier,
        )


def _canonical_uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return ""


def _plain_text(value) -> str:
    return html.unescape(str(value)).strip() if isinstance(value, str) else ""


def _iso_datetime(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return datetime.combine(parsed.date(), time.min, tzinfo=timezone.utc)
    return parsed


def _cpv_codes(value) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(dict.fromkeys(
        code for code in value.split() if len(code) == 8 and code.isdigit()
    ))


def _buyer_identifier(detail) -> str:
    if not isinstance(detail, dict):
        return ""
    releases = detail.get("releases")
    if not isinstance(releases, list) or not releases or not isinstance(releases[0], dict):
        return ""
    buyer = releases[0].get("buyer")
    if not isinstance(buyer, dict):
        return ""
    identifier = buyer.get("id")
    return str(identifier).strip()[:255] if isinstance(identifier, str) else ""
