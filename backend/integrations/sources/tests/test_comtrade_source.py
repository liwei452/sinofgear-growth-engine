from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from integrations.sources.base import SourceAdapterError, trade_governance_for
from integrations.sources.comtrade import ComtradeSource, TradeQuery


class RecordingTransport:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {"data": [], "datasetVersion": "2026-08-01"}
        self.error = error
        self.calls = []

    def get_json(self, *, url, timeout_seconds, max_response_bytes):
        self.calls.append({
            "url": url,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
        })
        if self.error:
            raise self.error
        return self.payload


def _row(**overrides):
    return {
        "reporterCode": 360,
        "reporterDesc": "Indonesia",
        "partnerCode": 0,
        "partnerDesc": "World",
        "flowCode": "M",
        "flowDesc": "Import",
        "cmdCode": "848340",
        "period": 2024,
        "primaryValue": 125000,
        "qty": 840,
        "qtyUnitAbbr": "kg",
        "isAggregate": True,
        **overrides,
    }


def test_comtrade_normalizes_annual_import_and_records_official_provenance():
    transport = RecordingTransport({
        "data": [_row()],
        "datasetVersion": "2026-08-01",
        "count": 1,
    })

    batch = ComtradeSource(transport=transport).fetch(TradeQuery(
        reporter_code="360",
        partner_code="0",
        flow="M",
        hs_codes=("848340",),
        periods=("2024",),
    ))

    assert len(batch.rows) == 1
    row = batch.rows[0]
    assert row.reporter_code == "360"
    assert row.reporter_name == "Indonesia"
    assert row.partner_code == "0"
    assert row.partner_name == "World"
    assert row.flow == "M"
    assert row.flow_name == "Import"
    assert row.hs_code == "848340"
    assert row.period == "2024"
    assert row.trade_value_usd == Decimal("125000")
    assert row.quantity == Decimal("840")
    assert row.quantity_unit == "kg"
    assert row.source_dataset == "UN_COMTRADE_PUBLIC"
    assert row.dataset_version == "2026-08-01"
    assert row.source_url.startswith("https://comtradeplus.un.org/")
    assert batch.total_count == 1
    assert batch.skipped_count == 0
    assert batch.capability_snapshot == {
        "source": "UN_COMTRADE",
        "capture_method": "OFFICIAL_PUBLIC_API",
        "authentication": "ANONYMOUS",
        "dataset_scope": "AGGREGATE_TRADE_ONLY",
        "result_limit": 500,
        "governance": trade_governance_for("UN_COMTRADE"),
    }


def test_comtrade_uses_only_fixed_official_host_and_bounded_query_parameters():
    transport = RecordingTransport()

    ComtradeSource(
        transport=transport,
        timeout_seconds=7,
        max_response_bytes=500_000,
    ).fetch(TradeQuery(
        reporter_code="710",
        partner_code="156",
        flow="M",
        hs_codes=("848340", "848390"),
        periods=("2023", "2024"),
    ))

    call = transport.calls[0]
    parsed = urlparse(call["url"])
    assert parsed.scheme == "https"
    assert parsed.hostname == "comtradeapi.un.org"
    assert parsed.path == "/public/v1/preview/C/A/HS"
    assert parse_qs(parsed.query) == {
        "reporterCode": ["710"],
        "partnerCode": ["156"],
        "flowCode": ["M"],
        "cmdCode": ["848340,848390"],
        "period": ["2023,2024"],
        "aggregateBy": ["6"],
        "breakdownMode": ["classic"],
        "includeDesc": ["true"],
    }
    assert call["timeout_seconds"] == 7
    assert call["max_response_bytes"] == 500_000


@pytest.mark.parametrize("hs_code", ["8483", "848340", "848390", "123456"])
def test_trade_query_accepts_default_and_custom_four_or_six_digit_hs(hs_code):
    query = TradeQuery(
        reporter_code="360",
        partner_code="0",
        flow="M",
        hs_codes=(hs_code,),
        periods=("2024",),
    )

    assert query.hs_codes == (hs_code,)


@pytest.mark.parametrize("hs_codes", [(), ("848",), ("84834X",), ("84834000",)])
def test_trade_query_rejects_missing_or_unbounded_hs_codes(hs_codes):
    with pytest.raises(ValueError, match="four or six digit"):
        TradeQuery(
            reporter_code="360",
            partner_code="0",
            flow="M",
            hs_codes=hs_codes,
            periods=("2024",),
        )


@pytest.mark.parametrize("periods", [(), ("24",), ("202413",), ("2024,2025",)])
def test_trade_query_rejects_invalid_periods(periods):
    with pytest.raises(ValueError, match="annual YYYY or monthly YYYYMM"):
        TradeQuery(
            reporter_code="360",
            partner_code="0",
            flow="M",
            hs_codes=("848340",),
            periods=periods,
        )


def test_comtrade_skips_malformed_non_aggregate_and_query_mismatch_rows():
    transport = RecordingTransport({
        "data": [
            _row(reporterCode=None),
            _row(cmdCode="999999"),
            _row(isAggregate=False),
            _row(primaryValue="not-a-number"),
            _row(period=2023),
        ],
        "datasetVersion": "2026-08-01",
        "count": 5,
    })

    batch = ComtradeSource(transport=transport).fetch(TradeQuery(
        reporter_code="360",
        partner_code="0",
        flow="M",
        hs_codes=("848340",),
        periods=("2024",),
    ))

    assert batch.rows == ()
    assert batch.skipped_count == 5
    assert batch.total_count == 5


@pytest.mark.parametrize(
    "error_code",
    [
        "SOURCE_UNAVAILABLE",
        "SOURCE_RATE_LIMITED",
        "SOURCE_RESPONSE_TOO_LARGE",
        "SOURCE_INVALID_RESPONSE",
    ],
)
def test_comtrade_does_not_hide_transport_failures(error_code):
    source = ComtradeSource(
        transport=RecordingTransport(error=SourceAdapterError(error_code))
    )

    with pytest.raises(SourceAdapterError, match=error_code):
        source.fetch(TradeQuery(
            reporter_code="360",
            partner_code="0",
            flow="M",
            hs_codes=("848340",),
            periods=("2024",),
        ))


def test_comtrade_rejects_non_object_and_non_list_responses():
    source = ComtradeSource(transport=RecordingTransport({"data": "invalid"}))

    with pytest.raises(SourceAdapterError, match="SOURCE_INVALID_RESPONSE"):
        source.fetch(TradeQuery(
            reporter_code="360",
            partner_code="0",
            flow="M",
            hs_codes=("848340",),
            periods=("2024",),
        ))
