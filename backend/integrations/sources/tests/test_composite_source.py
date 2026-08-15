from datetime import date, datetime, timezone

import pytest

from integrations.sources.base import (
    DiscoveryQuery,
    SourceAdapterError,
    SourceBatch,
    SourceItem,
)
from integrations.sources.composite import CompositeDiscoverySource


class FixtureSource:
    def __init__(self, source_code, batch=None, error=None):
        self.source_code = source_code
        self.batch = batch
        self.error = error

    def fetch(self, query):
        if self.error:
            raise self.error
        return self.batch


def _item(source_code, external_id):
    return SourceItem(
        source_code=source_code,
        external_id=external_id,
        buyer_name=f"{source_code} buyer",
        buyer_country="GBR" if source_code == "UK_CONTRACTS_FINDER" else "DEU",
        title=f"Notice {external_id}",
        published_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        deadline_at=None,
        source_url=f"https://example.invalid/{source_code}/{external_id}",
        cpv_codes=("42141300",),
    )


def _batch(source_code, *ids):
    return SourceBatch(
        items=tuple(_item(source_code, value) for value in ids),
        capability_snapshot={
            "source": source_code,
            "capture_method": "OFFICIAL_PUBLIC_API",
            "authentication": "ANONYMOUS",
            "result_limit": 4,
        },
        total_count=len(ids),
    )


def _query(limit=4):
    return DiscoveryQuery(
        cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=limit,
    )


def test_composite_interleaves_sources_and_preserves_capability_evidence():
    source = CompositeDiscoverySource((
        FixtureSource("TED", _batch("TED", "ted-1", "ted-2")),
        FixtureSource(
            "UK_CONTRACTS_FINDER",
            _batch("UK_CONTRACTS_FINDER", "uk-1", "uk-2"),
        ),
    ))

    batch = source.fetch(_query())

    assert [item.external_id for item in batch.items] == [
        "ted-1", "uk-1", "ted-2", "uk-2",
    ]
    assert batch.capability_snapshot == {
        "source": "OFFICIAL_PROCUREMENT",
        "capture_method": "OFFICIAL_PUBLIC_API",
        "authentication": "ANONYMOUS",
        "result_limit": 4,
        "sources": [
            _batch("TED", "x").capability_snapshot,
            _batch("UK_CONTRACTS_FINDER", "x").capability_snapshot,
        ],
        "failures": [],
    }
    assert batch.total_count == 4


def test_composite_keeps_success_when_one_source_fails():
    source = CompositeDiscoverySource((
        FixtureSource("TED", _batch("TED", "ted-1")),
        FixtureSource(
            "UK_CONTRACTS_FINDER",
            error=SourceAdapterError("SOURCE_RATE_LIMITED"),
        ),
    ))

    batch = source.fetch(_query())

    assert [item.external_id for item in batch.items] == ["ted-1"]
    assert batch.capability_snapshot["failures"] == [{
        "source": "UK_CONTRACTS_FINDER",
        "code": "SOURCE_RATE_LIMITED",
    }]


def test_composite_fails_only_when_every_source_fails():
    source = CompositeDiscoverySource((
        FixtureSource("TED", error=SourceAdapterError("SOURCE_UNAVAILABLE")),
        FixtureSource(
            "UK_CONTRACTS_FINDER",
            error=SourceAdapterError("SOURCE_RATE_LIMITED"),
        ),
    ))

    with pytest.raises(SourceAdapterError, match="SOURCE_UNAVAILABLE"):
        source.fetch(_query())
