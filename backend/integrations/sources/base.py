from dataclasses import dataclass
from datetime import date, datetime


ALLOWED_PROCUREMENT_FIELDS = (
    "buyer_identifier", "buyer_name", "buyer_country", "notice_title",
    "publication_date", "deadline_date", "cpv_codes", "source_url",
)
SOURCE_GOVERNANCE = {
    "TED": {
        "source_owner": "Publications Office of the European Union",
        "access_method": "OFFICIAL_PUBLIC_API",
        "license_contract": "TED_SEARCH_API_PUBLIC_DATA",
    },
    "UK_CONTRACTS_FINDER": {
        "source_owner": "UK Cabinet Office",
        "access_method": "OFFICIAL_PUBLIC_API",
        "license_contract": "OPEN_GOVERNMENT_LICENCE_3.0",
    },
}


def governance_for(source_code: str) -> dict[str, object]:
    source = SOURCE_GOVERNANCE[source_code]
    return {
        **source,
        "robots_policy": "API_NOT_WEB_SCRAPING",
        "rate_limit": "MAX_20_RESULTS_PER_RUN_DAILY_SCHEDULE",
        "allowed_fields": list(ALLOWED_PROCUREMENT_FIELDS),
        "retention_period": "365_DAYS_THEN_REVIEW",
        "redistribution_restriction": "SOURCE_LINK_AND_SHORT_EXCERPT_ONLY",
        "queue": "MONITORING",
    }


@dataclass(frozen=True)
class DiscoveryQuery:
    cpv_codes: tuple[str, ...]
    published_from: date
    limit: int = 20

    def __post_init__(self):
        if not 1 <= self.limit <= 20:
            raise ValueError("Discovery result limit must be between 1 and 20.")
        if not self.cpv_codes or any(
            len(code) != 8 or not code.isdigit() for code in self.cpv_codes
        ):
            raise ValueError("Discovery CPV codes must be eight digit values.")


@dataclass(frozen=True)
class SourceItem:
    source_code: str
    external_id: str
    buyer_name: str
    buyer_country: str
    title: str
    published_at: datetime
    deadline_at: datetime | None
    source_url: str
    cpv_codes: tuple[str, ...]
    buyer_identifier: str = ""


@dataclass(frozen=True)
class SourceBatch:
    items: tuple[SourceItem, ...]
    capability_snapshot: dict[str, object]
    skipped_count: int = 0
    total_count: int = 0
    is_demo: bool = False


class SourceAdapterError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
