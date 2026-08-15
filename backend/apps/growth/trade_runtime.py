from dataclasses import replace
from decimal import Decimal

from django.conf import settings

from integrations.sources.comtrade import (
    COMTRADE_SOURCE_URL,
    ComtradeSource,
    TradeBatch,
    TradeRow,
)


COUNTRY_REPORTER_CODES = {
    "USA": "842",
    "GBR": "826",
    "CAN": "124",
    "VNM": "704",
    "IDN": "360",
    "PHL": "608",
    "ZAF": "710",
    "EGY": "818",
    "KEN": "404",
    "NGA": "566",
    "MAR": "504",
    "CHL": "152",
    "PER": "604",
    "COL": "170",
    "MEX": "484",
    "BRA": "076",
    "IND": "356",
    "TUR": "792",
    "PAK": "586",
    "SAU": "682",
    "GHA": "288",
}


class TradeProviderConfigurationRequired(RuntimeError):
    pass


def trade_source_runtime():
    mode = getattr(settings, "PUBLIC_TRADE_PROVIDER_MODE", "DISABLED")
    if mode == "FIXTURE":
        return FixtureComtradeSource(), mode
    if mode == "OFFICIAL_PUBLIC":
        return ComtradeSource(), mode
    raise TradeProviderConfigurationRequired


class FixtureComtradeSource:
    source_code = "UN_COMTRADE"

    def fetch(self, query):
        if query.reporter_code != "360":
            return TradeBatch(
                rows=(), capability_snapshot=_capability(), skipped_count=0,
                total_count=0, is_demo=True,
            )
        values = {
            ("848340", "2023", "0"): "100000",
            ("848390", "2023", "0"): "80000",
            ("848340", "2024", "0"): "125000",
            ("848390", "2024", "0"): "100000",
            ("848340", "2024", "156"): "50000",
            ("848390", "2024", "156"): "40000",
        }
        rows = []
        for (hs_code, period, partner_code), value in values.items():
            if hs_code not in query.hs_codes or period not in query.periods:
                continue
            if partner_code != query.partner_code:
                continue
            rows.append(_fixture_row(
                reporter_code=query.reporter_code,
                partner_code=partner_code,
                hs_code=hs_code,
                period=period,
                value=value,
            ))
        return TradeBatch(
            rows=tuple(rows),
            capability_snapshot=_capability(),
            skipped_count=0,
            total_count=len(rows),
            is_demo=True,
        )


def _fixture_row(*, reporter_code, partner_code, hs_code, period, value):
    base = TradeRow(
        reporter_code=reporter_code,
        reporter_name="Demo Indonesia",
        partner_code=partner_code,
        partner_name="World" if partner_code == "0" else "China",
        flow="M",
        flow_name="Import",
        hs_code=hs_code,
        period=period,
        trade_value_usd=Decimal(value),
        quantity=None,
        quantity_unit="",
        source_url="",
        source_dataset="UN_COMTRADE_FIXTURE",
        dataset_version="FIXTURE-2026-08-16",
    )
    return replace(base, source_url=(
        f"{COMTRADE_SOURCE_URL}?reporterCode={reporter_code}"
        f"&partnerCode={partner_code}&flowCode=M&cmdCode={hs_code}&period={period}"
    ))


def _capability():
    return {
        "source": "UN_COMTRADE",
        "capture_method": "FIXTURE_TRANSPORT",
        "dataset_scope": "AGGREGATE_TRADE_ONLY",
        "is_demo": True,
    }
