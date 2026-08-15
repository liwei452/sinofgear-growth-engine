from datetime import date

import pytest

from integrations.sources.base import DiscoveryQuery
from integrations.sources.ted import TedSource


class RecordingTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post_json(self, *, url, payload, timeout_seconds, max_response_bytes):
        self.calls.append({
            "url": url,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
        })
        return self.payload


def _notice(**overrides):
    return {
        "publication-number": "534032-2026",
        "buyer-name": {"deu": ["Vergabestelle"], "eng": ["Example Contracting Authority"]},
        "buyer-country": ["DEU"],
        "notice-title": {"deu": "Zahnräder", "eng": "Industrial gears"},
        "publication-date": "2026-08-03+02:00",
        "deadline-receipt-tender-date-lot": ["2026-09-08+02:00"],
        "classification-cpv": ["42141300", "42142000"],
        "links": {
            "html": {"ENG": "https://ted.europa.eu/en/notice/-/detail/534032-2026"},
        },
        **overrides,
    }


def test_ted_source_normalizes_an_official_notice_and_uses_bounded_query():
    transport = RecordingTransport({"notices": [_notice()], "totalNoticeCount": 1, "timedOut": False})

    batch = TedSource(transport=transport).fetch(
        DiscoveryQuery(
            cpv_codes=("42141300", "42142000"),
            published_from=date(2026, 8, 1),
            limit=10,
        )
    )

    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.external_id == "534032-2026"
    assert item.buyer_name == "Example Contracting Authority"
    assert item.buyer_country == "DEU"
    assert item.title == "Industrial gears"
    assert item.source_url == "https://ted.europa.eu/en/notice/-/detail/534032-2026"
    assert item.cpv_codes == ("42141300", "42142000")
    assert item.deadline_at is not None
    assert batch.capability_snapshot == {
        "source": "TED",
        "capture_method": "OFFICIAL_PUBLIC_API",
        "authentication": "ANONYMOUS",
        "result_limit": 10,
    }
    call = transport.calls[0]
    assert call["url"] == "https://api.ted.europa.eu/v3/notices/search"
    assert call["timeout_seconds"] == 15
    assert call["max_response_bytes"] == 2_000_000
    assert call["payload"]["limit"] == 10
    assert "classification-cpv IN (42141300 42142000)" in call["payload"]["query"]
    assert "publication-date >= 20260801" in call["payload"]["query"]


def test_ted_source_skips_records_without_a_buyer_or_safe_original_link():
    transport = RecordingTransport({
        "notices": [
            _notice(**{"buyer-name": {}}),
            _notice(**{"publication-number": "534033-2026", "links": {"html": {"ENG": "http://ted.europa.eu/unsafe"}}}),
        ],
        "totalNoticeCount": 2,
        "timedOut": False,
    })

    batch = TedSource(transport=transport).fetch(
        DiscoveryQuery(cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=20)
    )

    assert batch.items == ()
    assert batch.skipped_count == 2


def test_ted_source_accepts_bounded_operator_timeout_and_response_limits():
    transport = RecordingTransport({"notices": [], "totalNoticeCount": 0, "timedOut": False})

    TedSource(
        transport=transport,
        timeout_seconds=7,
        max_response_bytes=500_000,
    ).fetch(DiscoveryQuery(
        cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=5,
    ))

    assert transport.calls[0]["timeout_seconds"] == 7
    assert transport.calls[0]["max_response_bytes"] == 500_000


@pytest.mark.parametrize("limit", [0, 21])
def test_discovery_query_rejects_unbounded_result_limits(limit):
    with pytest.raises(ValueError, match="between 1 and 20"):
        DiscoveryQuery(cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=limit)
