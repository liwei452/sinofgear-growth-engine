from dataclasses import replace
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.growth.models import (
    IntentSignal,
    TargetAccount,
    TradeDatasetSnapshot,
    TradeSyncRun,
)
from apps.growth.trade_data import sync_trade_data, trade_indicators
from apps.identity.models import Organization
from integrations.sources.base import SourceAdapterError
from integrations.sources.comtrade import TradeBatch, TradeQuery, TradeRow


class FakeTradeSource:
    source_code = "UN_COMTRADE"

    def __init__(self, batch=None, error=None):
        self.batch = batch
        self.error = error

    def fetch(self, query):
        if self.error:
            raise self.error
        return self.batch


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Trade radar", slug="trade-radar")


@pytest.fixture
def actor(db):
    return get_user_model().objects.create_user(username="trade-operator")


def _row(**overrides):
    values = {
        "reporter_code": "360",
        "reporter_name": "Indonesia",
        "partner_code": "0",
        "partner_name": "World",
        "flow": "M",
        "flow_name": "Import",
        "hs_code": "848340",
        "period": "2024",
        "trade_value_usd": Decimal("125000"),
        "quantity": Decimal("840"),
        "quantity_unit": "kg",
        "source_url": (
            "https://comtradeplus.un.org/TradeFlow?reporterCode=360&partnerCode=0"
            "&flowCode=M&cmdCode=848340&period=2024"
        ),
        "source_dataset": "UN_COMTRADE_PUBLIC",
        "dataset_version": "2026-08-01",
    }
    values.update(overrides)
    return TradeRow(**values)


def _batch(*rows):
    return TradeBatch(
        rows=tuple(rows),
        capability_snapshot={
            "source": "UN_COMTRADE",
            "capture_method": "OFFICIAL_PUBLIC_API",
            "dataset_scope": "AGGREGATE_TRADE_ONLY",
        },
        skipped_count=0,
        total_count=len(rows),
    )


def _query():
    return TradeQuery(
        reporter_code="360",
        partner_code="0",
        flow="M",
        hs_codes=("848340",),
        periods=("2023", "2024"),
    )


@pytest.mark.django_db
def test_sync_persists_immutable_aggregate_snapshot_without_creating_buyers(
    organization, actor,
):
    result = sync_trade_data(
        organization=organization,
        actor=actor,
        query=_query(),
        source=FakeTradeSource(_batch(_row())),
    )

    snapshot = TradeDatasetSnapshot.objects.get(organization=organization)
    run = TradeSyncRun.objects.get(organization=organization)
    assert result.snapshot_ids == (snapshot.id,)
    assert snapshot.first_seen_run == run
    assert snapshot.reporter_code == "360"
    assert snapshot.partner_code == "0"
    assert snapshot.hs_code == "848340"
    assert snapshot.period == "2024"
    assert snapshot.trade_value_usd == Decimal("125000")
    assert snapshot.quantity == Decimal("840")
    assert snapshot.source_url.startswith("https://comtradeplus.un.org/")
    assert snapshot.source_dataset == "UN_COMTRADE_PUBLIC"
    assert snapshot.dataset_version == "2026-08-01"
    assert snapshot.observed_at.isoformat() == "2024-12-31"
    assert snapshot.record_hash and len(snapshot.record_hash) == 64
    assert snapshot.provenance["scope"] == "AGGREGATE_MARKET_CONTEXT_ONLY"
    assert snapshot.provenance["not_company_evidence"] is True
    assert run.status == TradeSyncRun.Status.SUCCEEDED
    assert run.created_snapshot_count == 1
    assert run.reused_snapshot_count == 0
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    assert IntentSignal.objects.filter(organization=organization).count() == 0


@pytest.mark.django_db
def test_identical_rerun_reuses_snapshot_and_keeps_separate_run_audit(
    organization, actor,
):
    source = FakeTradeSource(_batch(_row()))

    first = sync_trade_data(
        organization=organization, actor=actor, query=_query(), source=source,
    )
    second = sync_trade_data(
        organization=organization, actor=actor, query=_query(), source=source,
    )

    assert first.snapshot_ids == second.snapshot_ids
    assert TradeDatasetSnapshot.objects.filter(organization=organization).count() == 1
    assert TradeSyncRun.objects.filter(organization=organization).count() == 2
    latest_run = TradeSyncRun.objects.order_by("-created_at", "-id").first()
    assert latest_run.created_snapshot_count == 0
    assert latest_run.reused_snapshot_count == 1


@pytest.mark.django_db
def test_changed_official_revision_creates_new_snapshot_without_overwriting_history(
    organization, actor,
):
    original = _row()
    revised = replace(
        original,
        trade_value_usd=Decimal("130000"),
        dataset_version="2026-08-15",
    )

    first = sync_trade_data(
        organization=organization,
        actor=actor,
        query=_query(),
        source=FakeTradeSource(_batch(original)),
    )
    second = sync_trade_data(
        organization=organization,
        actor=actor,
        query=_query(),
        source=FakeTradeSource(_batch(revised)),
    )

    assert first.snapshot_ids != second.snapshot_ids
    assert set(TradeDatasetSnapshot.objects.values_list("trade_value_usd", flat=True)) == {
        Decimal("125000"), Decimal("130000"),
    }


@pytest.mark.django_db
def test_snapshots_and_metrics_are_organization_isolated(organization, actor):
    other = Organization.objects.create(name="Other trade radar", slug="other-trade-radar")
    sync_trade_data(
        organization=organization,
        actor=actor,
        query=_query(),
        source=FakeTradeSource(_batch(_row())),
    )

    assert TradeDatasetSnapshot.objects.filter(organization=other).count() == 0
    result = trade_indicators(
        organization=other,
        reporter_code="360",
        hs_codes=("848340",),
        periods=("2023", "2024"),
        as_of=datetime(2026, 8, 16, tzinfo=dt_timezone.utc),
    )
    assert result["status"] == "NO_DATA"
    assert result["evidence"] == []


@pytest.mark.django_db
def test_source_failure_is_audited_without_partial_snapshots(organization, actor):
    with pytest.raises(SourceAdapterError, match="SOURCE_RATE_LIMITED"):
        sync_trade_data(
            organization=organization,
            actor=actor,
            query=_query(),
            source=FakeTradeSource(error=SourceAdapterError("SOURCE_RATE_LIMITED")),
        )

    run = TradeSyncRun.objects.get(organization=organization)
    assert run.status == TradeSyncRun.Status.FAILED
    assert run.error_code == "SOURCE_RATE_LIMITED"
    assert run.finished_at is not None
    assert TradeDatasetSnapshot.objects.filter(organization=organization).count() == 0


@pytest.mark.django_db
def test_indicators_show_literal_formula_inputs_and_source_evidence(organization, actor):
    rows = (
        _row(period="2023", trade_value_usd=Decimal("100000")),
        _row(period="2024", trade_value_usd=Decimal("125000")),
        _row(
            partner_code="156",
            partner_name="China",
            period="2024",
            trade_value_usd=Decimal("50000"),
            source_url=(
                "https://comtradeplus.un.org/TradeFlow?reporterCode=360&partnerCode=156"
                "&flowCode=M&cmdCode=848340&period=2024"
            ),
        ),
    )
    world_query = _query()
    china_query = replace(world_query, partner_code="156", periods=("2024",))
    sync_trade_data(
        organization=organization,
        actor=actor,
        query=world_query,
        source=FakeTradeSource(_batch(*rows[:2])),
    )
    sync_trade_data(
        organization=organization,
        actor=actor,
        query=china_query,
        source=FakeTradeSource(_batch(rows[2])),
    )

    result = trade_indicators(
        organization=organization,
        reporter_code="360",
        hs_codes=("848340",),
        periods=("2023", "2024"),
        as_of=datetime(2026, 8, 16, tzinfo=dt_timezone.utc),
    )

    assert result["status"] == "READY"
    assert result["scope_warning"] == "AGGREGATE_TRADE_IS_NOT_COMPANY_BUYER_EVIDENCE"
    assert result["indicators"]["import_scale"] == {
        "formula": "sum(latest world import values)",
        "value_usd": "125000.00",
        "inputs": {"period": "2024", "world_values": ["125000.00"]},
    }
    assert result["indicators"]["year_over_year"] == {
        "formula": "(current - previous) / previous * 100",
        "value_percent": "25.00",
        "inputs": {"current": "125000.00", "previous": "100000.00"},
    }
    assert result["indicators"]["continuity"] == {
        "formula": "observed requested periods / requested periods * 100",
        "value_percent": "100.00",
        "inputs": {"observed_periods": ["2023", "2024"], "requested_periods": ["2023", "2024"]},
    }
    assert result["indicators"]["china_share"] == {
        "formula": "China import value / world import value * 100",
        "value_percent": "40.00",
        "inputs": {"china_value": "50000.00", "world_value": "125000.00"},
    }
    assert result["indicators"]["freshness"]["formula"] == "as_of date - latest observed period end"
    assert result["indicators"]["freshness"]["value_days"] == 593
    assert len(result["evidence"]) == 3
    assert {item["source_dataset"] for item in result["evidence"]} == {"UN_COMTRADE_PUBLIC"}


@pytest.mark.django_db
def test_missing_or_zero_denominator_returns_unknown_not_misleading_zero(
    organization, actor,
):
    sync_trade_data(
        organization=organization,
        actor=actor,
        query=_query(),
        source=FakeTradeSource(_batch(_row(trade_value_usd=Decimal("0")))),
    )

    result = trade_indicators(
        organization=organization,
        reporter_code="360",
        hs_codes=("848340",),
        periods=("2023", "2024"),
        as_of=datetime(2026, 8, 16, tzinfo=dt_timezone.utc),
    )

    assert result["indicators"]["year_over_year"]["value_percent"] is None
    assert result["indicators"]["year_over_year"]["reason"] == "PREVIOUS_PERIOD_MISSING_OR_ZERO"
    assert result["indicators"]["china_share"]["value_percent"] is None
    assert result["indicators"]["china_share"]["reason"] == "CHINA_OR_WORLD_VALUE_MISSING_OR_ZERO"
