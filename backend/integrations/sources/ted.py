import json
from datetime import date, datetime, time, timezone
from http.client import HTTPResponse
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import DiscoveryQuery, SourceAdapterError, SourceBatch, SourceItem


TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_TIMEOUT_SECONDS = 15
TED_MAX_RESPONSE_BYTES = 2_000_000
TED_FIELDS = (
    "publication-number",
    "buyer-name",
    "buyer-country",
    "notice-title",
    "publication-date",
    "deadline-receipt-tender-date-lot",
    "classification-cpv",
)


class JsonTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, object]: ...


class UrllibJsonTransport:
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response: HTTPResponse
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed trusted URL
                body = response.read(max_response_bytes + 1)
        except HTTPError as error:
            if error.code == 429:
                raise SourceAdapterError("SOURCE_RATE_LIMITED") from error
            if error.code >= 500:
                raise SourceAdapterError("SOURCE_UNAVAILABLE") from error
            raise SourceAdapterError("SOURCE_REJECTED_QUERY") from error
        except (TimeoutError, URLError) as error:
            raise SourceAdapterError("SOURCE_UNAVAILABLE") from error
        if len(body) > max_response_bytes:
            raise SourceAdapterError("SOURCE_RESPONSE_TOO_LARGE")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE") from error
        if not isinstance(decoded, dict):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        return decoded


class TedSource:
    def __init__(self, *, transport: JsonTransport | None = None):
        self.transport = transport or UrllibJsonTransport()

    def fetch(self, query: DiscoveryQuery) -> SourceBatch:
        cpv_query = " ".join(query.cpv_codes)
        payload = {
            "query": (
                f"classification-cpv IN ({cpv_query}) AND "
                f"publication-date >= {query.published_from:%Y%m%d}"
            ),
            "fields": list(TED_FIELDS),
            "page": 1,
            "limit": query.limit,
            "scope": "ACTIVE",
            "paginationMode": "PAGE_NUMBER",
            "onlyLatestVersions": True,
        }
        decoded = self.transport.post_json(
            url=TED_SEARCH_URL,
            payload=payload,
            timeout_seconds=TED_TIMEOUT_SECONDS,
            max_response_bytes=TED_MAX_RESPONSE_BYTES,
        )
        if decoded.get("timedOut") is True:
            raise SourceAdapterError("SOURCE_TIMED_OUT")
        notices = decoded.get("notices", [])
        if not isinstance(notices, list):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        items = []
        skipped_count = 0
        for notice in notices[: query.limit]:
            item = self._normalize_notice(notice)
            if item is None:
                skipped_count += 1
            else:
                items.append(item)
        return SourceBatch(
            items=tuple(items),
            capability_snapshot={
                "source": "TED",
                "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS",
                "result_limit": query.limit,
            },
            skipped_count=skipped_count,
            total_count=int(decoded.get("totalNoticeCount") or len(notices)),
        )

    @staticmethod
    def _normalize_notice(notice) -> SourceItem | None:
        if not isinstance(notice, dict):
            return None
        external_id = str(notice.get("publication-number") or "").strip()
        buyer_name = _multilingual_text(notice.get("buyer-name"), list_values=True)
        title = _multilingual_text(notice.get("notice-title"), list_values=False)
        source_url = _english_ted_link(notice.get("links"))
        published_at = _date_at_utc(notice.get("publication-date"))
        if not all((external_id, buyer_name, title, source_url, published_at)):
            return None
        countries = notice.get("buyer-country") or []
        country = str(countries[0]).strip() if isinstance(countries, list) and countries else ""
        deadlines = notice.get("deadline-receipt-tender-date-lot") or []
        deadline_at = _date_at_utc(deadlines[0]) if isinstance(deadlines, list) and deadlines else None
        cpv_values = notice.get("classification-cpv") or []
        cpv_codes = tuple(dict.fromkeys(
            str(code) for code in cpv_values
            if isinstance(code, str) and len(code) == 8 and code.isdigit()
        ))
        return SourceItem(
            external_id=external_id,
            buyer_name=buyer_name,
            buyer_country=country,
            title=title,
            published_at=published_at,
            deadline_at=deadline_at,
            source_url=source_url,
            cpv_codes=cpv_codes,
        )


def _multilingual_text(value, *, list_values: bool) -> str:
    if not isinstance(value, dict):
        return ""
    keys = ["eng", *sorted(key for key in value if key != "eng")]
    for key in keys:
        candidate = value.get(key)
        if list_values:
            if isinstance(candidate, list) and candidate and isinstance(candidate[0], str):
                return candidate[0].strip()
        elif isinstance(candidate, str):
            return candidate.strip()
    return ""


def _english_ted_link(value) -> str:
    if not isinstance(value, dict):
        return ""
    for group_name in ("html", "htmlDirect"):
        group = value.get(group_name)
        if not isinstance(group, dict):
            continue
        candidate = group.get("ENG") or next(iter(group.values()), "")
        if not isinstance(candidate, str):
            continue
        parsed = urlparse(candidate)
        if parsed.scheme == "https" and parsed.hostname == "ted.europa.eu":
            return candidate
    return ""


def _date_at_utc(value) -> datetime | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)

