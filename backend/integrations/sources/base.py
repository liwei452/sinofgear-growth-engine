from dataclasses import dataclass
from datetime import date, datetime


ALLOWED_PROCUREMENT_FIELDS = (
    "buyer_identifier", "buyer_name", "buyer_country", "notice_title",
    "publication_date", "deadline_date", "cpv_codes", "source_url",
)
ALLOWED_TRADE_FIELDS = (
    "reporter_code", "reporter_name", "partner_code", "partner_name",
    "flow", "flow_name", "hs_code", "period", "trade_value_usd",
    "quantity", "quantity_unit", "source_url", "source_dataset",
    "dataset_version",
)
ALLOWED_MAPS_FIELDS = (
    "place_id", "name", "address", "website", "phone", "primary_type",
    "types", "country_code", "source_url",
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
    "UN_COMTRADE": {
        "source_owner": "United Nations Statistics Division",
        "access_method": "OFFICIAL_PUBLIC_API",
        "license_contract": "UN_COMTRADE_PUBLIC_API_TERMS_REVIEW_REQUIRED",
    },
    "GOOGLE_MAPS": {
        "source_owner": "Google LLC",
        "access_method": "OFFICIAL_PUBLIC_API",
        "license_contract": "GOOGLE_MAPS_PLATFORM_TERMS",
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


def trade_governance_for(source_code: str) -> dict[str, object]:
    if source_code != "UN_COMTRADE":
        raise KeyError(source_code)
    source = SOURCE_GOVERNANCE[source_code]
    return {
        **source,
        "robots_policy": "API_NOT_WEB_SCRAPING",
        "rate_limit": "PUBLIC_API_LIMITS_AND_DAILY_SCHEDULE",
        "allowed_fields": list(ALLOWED_TRADE_FIELDS),
        "retention_period": "365_DAYS_THEN_REVIEW",
        "redistribution_restriction": "AGGREGATES_WITH_SOURCE_ATTRIBUTION_ONLY",
        "queue": "MARKET_RESEARCH",
    }


def maps_governance_for(source_code: str) -> dict[str, object]:
    if source_code != "GOOGLE_MAPS":
        raise KeyError(source_code)
    source = SOURCE_GOVERNANCE[source_code]
    return {
        **source,
        "robots_policy": "API_NOT_WEB_SCRAPING",
        "rate_limit": "PLACES_API_QUOTA_AND_DAILY_SCHEDULE",
        "allowed_fields": list(ALLOWED_MAPS_FIELDS),
        "retention_period": "PLACE_ID_INDEFINITE_OTHER_FIELDS_30_DAYS",
        "redistribution_restriction": "NO_REDISTRIBUTION_OF_GOOGLE_CONTENT",
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
