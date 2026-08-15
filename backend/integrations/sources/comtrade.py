from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlencode

from .base import SourceAdapterError, trade_governance_for
from .ted import UrllibJsonTransport


COMTRADE_API_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
COMTRADE_SOURCE_URL = "https://comtradeplus.un.org/TradeFlow"
COMTRADE_TIMEOUT_SECONDS = 15
COMTRADE_MAX_RESPONSE_BYTES = 2_000_000
COMTRADE_RESULT_LIMIT = 500


class JsonGetTransport(Protocol):
    def get_json(
        self,
        *,
        url: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class TradeQuery:
    reporter_code: str
    partner_code: str
    flow: str
    hs_codes: tuple[str, ...]
    periods: tuple[str, ...]

    def __post_init__(self):
        if not self.reporter_code.isdigit() or not 1 <= len(self.reporter_code) <= 3:
            raise ValueError("Reporter code must be a one to three digit M49 code.")
        if not self.partner_code.isdigit() or not 1 <= len(self.partner_code) <= 3:
            raise ValueError("Partner code must be a one to three digit M49 code.")
        if self.flow not in {"M", "X"}:
            raise ValueError("Trade flow must be M or X.")
        if (
            not self.hs_codes
            or len(self.hs_codes) > 10
            or any(len(code) not in {4, 6} or not code.isdigit() for code in self.hs_codes)
        ):
            raise ValueError("HS codes must be one to ten four or six digit values.")
        if (
            not self.periods
            or len(self.periods) > 24
            or any(not _valid_period(period) for period in self.periods)
        ):
            raise ValueError("Periods must be annual YYYY or monthly YYYYMM values.")


@dataclass(frozen=True)
class TradeRow:
    reporter_code: str
    reporter_name: str
    partner_code: str
    partner_name: str
    flow: str
    flow_name: str
    hs_code: str
    period: str
    trade_value_usd: Decimal
    quantity: Decimal | None
    quantity_unit: str
    source_url: str
    source_dataset: str
    dataset_version: str


@dataclass(frozen=True)
class TradeBatch:
    rows: tuple[TradeRow, ...]
    capability_snapshot: dict[str, object]
    skipped_count: int
    total_count: int


class ComtradeSource:
    source_code = "UN_COMTRADE"

    def __init__(
        self,
        *,
        transport: JsonGetTransport | None = None,
        timeout_seconds: int = COMTRADE_TIMEOUT_SECONDS,
        max_response_bytes: int = COMTRADE_MAX_RESPONSE_BYTES,
    ):
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Comtrade timeout must be between 1 and 30 seconds.")
        if not 100_000 <= max_response_bytes <= COMTRADE_MAX_RESPONSE_BYTES:
            raise ValueError(
                "Comtrade response limit must be between 100000 and 2000000 bytes."
            )
        self.transport = transport or UrllibJsonTransport()
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def fetch(self, query: TradeQuery) -> TradeBatch:
        params = {
            "reporterCode": query.reporter_code,
            "partnerCode": query.partner_code,
            "flowCode": query.flow,
            "cmdCode": ",".join(query.hs_codes),
            "period": ",".join(query.periods),
            "aggregateBy": "6",
            "breakdownMode": "classic",
            "includeDesc": "true",
        }
        decoded = self.transport.get_json(
            url=f"{COMTRADE_API_URL}?{urlencode(params)}",
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        raw_rows = decoded["data"][:COMTRADE_RESULT_LIMIT]
        dataset_version = _bounded_text(decoded.get("datasetVersion"), 100)
        rows = []
        skipped_count = 0
        for raw_row in raw_rows:
            row = _normalize_row(raw_row, query=query, dataset_version=dataset_version)
            if row is None:
                skipped_count += 1
            else:
                rows.append(row)
        total_count = decoded.get("count")
        if not isinstance(total_count, int) or total_count < 0:
            total_count = len(decoded["data"])
        return TradeBatch(
            rows=tuple(rows),
            capability_snapshot={
                "source": self.source_code,
                "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS",
                "dataset_scope": "AGGREGATE_TRADE_ONLY",
                "result_limit": COMTRADE_RESULT_LIMIT,
                "governance": trade_governance_for(self.source_code),
            },
            skipped_count=skipped_count,
            total_count=total_count,
        )


def _normalize_row(raw_row, *, query: TradeQuery, dataset_version: str) -> TradeRow | None:
    if not isinstance(raw_row, dict) or raw_row.get("isAggregate") is not True:
        return None
    reporter_code = _code(raw_row.get("reporterCode"))
    partner_code = _code(raw_row.get("partnerCode"))
    flow = _bounded_text(raw_row.get("flowCode"), 2)
    hs_code = _bounded_text(raw_row.get("cmdCode"), 6)
    period = _bounded_text(raw_row.get("period"), 6)
    if (
        reporter_code != query.reporter_code
        or partner_code != query.partner_code
        or flow != query.flow
        or hs_code not in query.hs_codes
        or period not in query.periods
    ):
        return None
    trade_value = _decimal(raw_row.get("primaryValue"), required=True)
    if trade_value is None:
        return None
    quantity = _decimal(raw_row.get("qty"), required=False)
    source_params = urlencode({
        "reporterCode": reporter_code,
        "partnerCode": partner_code,
        "flowCode": flow,
        "cmdCode": hs_code,
        "period": period,
    })
    return TradeRow(
        reporter_code=reporter_code,
        reporter_name=_bounded_text(raw_row.get("reporterDesc"), 200),
        partner_code=partner_code,
        partner_name=_bounded_text(raw_row.get("partnerDesc"), 200),
        flow=flow,
        flow_name=_bounded_text(raw_row.get("flowDesc"), 40),
        hs_code=hs_code,
        period=period,
        trade_value_usd=trade_value,
        quantity=quantity,
        quantity_unit=_bounded_text(raw_row.get("qtyUnitAbbr"), 40),
        source_url=f"{COMTRADE_SOURCE_URL}?{source_params}",
        source_dataset="UN_COMTRADE_PUBLIC",
        dataset_version=dataset_version,
    )


def _valid_period(value: str) -> bool:
    if not isinstance(value, str) or not value.isdigit():
        return False
    if len(value) == 4:
        return 1962 <= int(value) <= 2100
    if len(value) == 6:
        return 1962 <= int(value[:4]) <= 2100 and 1 <= int(value[4:]) <= 12
    return False


def _code(value) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (str, int)):
        text = str(value).strip()
        if text.isdigit() and 1 <= len(text) <= 3:
            return text
    return ""


def _bounded_text(value, maximum: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    text = str(value).strip()
    return text if len(text) <= maximum else ""


def _decimal(value, *, required: bool) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed
