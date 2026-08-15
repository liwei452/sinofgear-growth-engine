import calendar
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from apps.growth.models import TradeDatasetSnapshot, TradeSyncRun
from integrations.sources.base import SourceAdapterError
from integrations.sources.comtrade import TradeQuery, TradeRow


@dataclass(frozen=True)
class TradeSyncResult:
    run_id: object
    snapshot_ids: tuple[object, ...]


def sync_trade_data(*, organization, actor, query: TradeQuery, source) -> TradeSyncResult:
    query_snapshot = {
        "reporter_code": query.reporter_code,
        "partner_code": query.partner_code,
        "flow": query.flow,
        "hs_codes": list(query.hs_codes),
        "periods": list(query.periods),
    }
    run = TradeSyncRun.objects.create(
        organization=organization,
        actor=actor,
        source_code=source.source_code,
        trigger=TradeSyncRun.Trigger.MANUAL,
        status=TradeSyncRun.Status.RUNNING,
        query_snapshot=query_snapshot,
        query_hash=_sha256(query_snapshot),
    )
    try:
        batch = source.fetch(query)
        fetched_at = timezone.now()
        snapshot_ids = []
        created_count = 0
        reused_count = 0
        with transaction.atomic():
            for row in batch.rows:
                record = _snapshot_record(
                    row, fetched_at=fetched_at, is_demo=batch.is_demo,
                )
                snapshot, created = TradeDatasetSnapshot.objects.get_or_create(
                    organization=organization,
                    record_hash=record["record_hash"],
                    defaults={"first_seen_run": run, **record},
                )
                snapshot_ids.append(snapshot.id)
                created_count += int(created)
                reused_count += int(not created)
            run.status = TradeSyncRun.Status.SUCCEEDED
            run.capability_snapshot = batch.capability_snapshot
            run.fetched_count = batch.total_count
            run.created_snapshot_count = created_count
            run.reused_snapshot_count = reused_count
            run.skipped_count = batch.skipped_count
            run.finished_at = fetched_at
            run.save(update_fields=[
                "status", "capability_snapshot", "fetched_count",
                "created_snapshot_count", "reused_snapshot_count", "skipped_count",
                "finished_at", "updated_at",
            ])
        return TradeSyncResult(run_id=run.id, snapshot_ids=tuple(snapshot_ids))
    except SourceAdapterError as error:
        run.status = TradeSyncRun.Status.FAILED
        run.error_code = error.code
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_code", "finished_at", "updated_at"])
        raise


def trade_indicators(
    *, organization, reporter_code: str, hs_codes: tuple[str, ...],
    periods: tuple[str, ...], as_of: datetime | None = None,
) -> dict[str, object]:
    snapshots = list(TradeDatasetSnapshot.objects.filter(
        organization=organization,
        reporter_code=reporter_code,
        flow="M",
        hs_code__in=hs_codes,
        period__in=periods,
        partner_code__in=("0", "156"),
    ).order_by("-created_at", "-id"))
    if not snapshots:
        return {
            "status": "NO_DATA",
            "scope_warning": "AGGREGATE_TRADE_IS_NOT_COMPANY_BUYER_EVIDENCE",
            "indicators": {},
            "evidence": [],
        }

    latest_by_dimension = {}
    for snapshot in snapshots:
        key = (
            snapshot.reporter_code, snapshot.partner_code, snapshot.flow,
            snapshot.hs_code, snapshot.period,
        )
        latest_by_dimension.setdefault(key, snapshot)
    selected = list(latest_by_dimension.values())
    world = [item for item in selected if item.partner_code == "0"]
    china = [item for item in selected if item.partner_code == "156"]
    observed_periods = sorted({item.period for item in world})
    latest_period = max(observed_periods)
    previous_period = _previous_period(latest_period)
    current_value = _sum_values(world, latest_period)
    previous_value = _sum_values(world, previous_period)
    china_value = _sum_values(china, latest_period)
    yoy_value = _percent(current_value - previous_value, previous_value) if previous_value else None
    china_share = _percent(china_value, current_value) if china_value is not None and current_value else None
    continuity = _percent(
        Decimal(len(set(periods) & set(observed_periods))), Decimal(len(set(periods)))
    )
    latest_observed = max(item.observed_at for item in selected)
    reference_date = (as_of or timezone.now()).date()

    indicators = {
        "import_scale": {
            "formula": "sum(latest world import values)",
            "value_usd": _money(current_value),
            "inputs": {
                "period": latest_period,
                "world_values": [
                    _money(item.trade_value_usd)
                    for item in world if item.period == latest_period
                ],
            },
        },
        "year_over_year": {
            "formula": "(current - previous) / previous * 100",
            "value_percent": _number(yoy_value),
            "inputs": {"current": _money(current_value), "previous": _money(previous_value)},
        },
        "continuity": {
            "formula": "observed requested periods / requested periods * 100",
            "value_percent": _number(continuity),
            "inputs": {
                "observed_periods": observed_periods,
                "requested_periods": list(periods),
            },
        },
        "freshness": {
            "formula": "as_of date - latest observed period end",
            "value_days": max((reference_date - latest_observed).days, 0),
            "inputs": {
                "as_of": reference_date.isoformat(),
                "latest_observed_at": latest_observed.isoformat(),
            },
        },
        "china_share": {
            "formula": "China import value / world import value * 100",
            "value_percent": _number(china_share),
            "inputs": {
                "china_value": _money(china_value),
                "world_value": _money(current_value),
            },
        },
    }
    if yoy_value is None:
        indicators["year_over_year"]["reason"] = "PREVIOUS_PERIOD_MISSING_OR_ZERO"
    if china_share is None:
        indicators["china_share"]["reason"] = "CHINA_OR_WORLD_VALUE_MISSING_OR_ZERO"
    evidence = [{
        "id": str(item.id),
        "reporter_code": item.reporter_code,
        "partner_code": item.partner_code,
        "hs_code": item.hs_code,
        "period": item.period,
        "trade_value_usd": _money(item.trade_value_usd),
        "source_url": item.source_url,
        "source_dataset": item.source_dataset,
        "dataset_version": item.dataset_version,
        "fetched_at": item.fetched_at.isoformat(),
        "is_demo": item.is_demo,
    } for item in sorted(selected, key=lambda value: (value.period, value.partner_code, value.hs_code))]
    return {
        "status": "READY",
        "scope_warning": "AGGREGATE_TRADE_IS_NOT_COMPANY_BUYER_EVIDENCE",
        "indicators": indicators,
        "evidence": evidence,
    }


def _snapshot_record(
    row: TradeRow, *, fetched_at: datetime, is_demo: bool,
) -> dict[str, object]:
    observed_at = _period_end(row.period)
    canonical = {
        "reporter_code": row.reporter_code,
        "reporter_name": row.reporter_name,
        "partner_code": row.partner_code,
        "partner_name": row.partner_name,
        "flow": row.flow,
        "flow_name": row.flow_name,
        "hs_code": row.hs_code,
        "period": row.period,
        "trade_value_usd": str(row.trade_value_usd),
        "quantity": str(row.quantity) if row.quantity is not None else None,
        "quantity_unit": row.quantity_unit,
        "source_url": row.source_url,
        "source_dataset": row.source_dataset,
        "dataset_version": row.dataset_version,
        "is_demo": is_demo,
    }
    return {
        **canonical,
        "frequency": "ANNUAL" if len(row.period) == 4 else "MONTHLY",
        "observed_at": observed_at,
        "fetched_at": fetched_at,
        "freshness_days": max((fetched_at.date() - observed_at).days, 0),
        "record_hash": _sha256(canonical),
        "provenance": {
            "scope": "AGGREGATE_MARKET_CONTEXT_ONLY",
            "not_company_evidence": True,
            "source_url": row.source_url,
            "source_dataset": row.source_dataset,
            "dataset_version": row.dataset_version,
            "is_demo": is_demo,
        },
        "is_demo": is_demo,
    }


def _period_end(period: str) -> date:
    if len(period) == 4:
        return date(int(period), 12, 31)
    year, month = int(period[:4]), int(period[4:])
    return date(year, month, calendar.monthrange(year, month)[1])


def _previous_period(period: str) -> str:
    if len(period) == 4:
        return str(int(period) - 1)
    year, month = int(period[:4]), int(period[4:])
    if month == 1:
        return f"{year - 1}12"
    return f"{year}{month - 1:02d}"


def _sum_values(items, period: str) -> Decimal | None:
    values = [item.trade_value_usd for item in items if item.period == period]
    return sum(values, Decimal("0")) if values else None


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


def _money(value: Decimal | None) -> str | None:
    return format(value.quantize(Decimal("0.01")), "f") if value is not None else None


def _number(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
