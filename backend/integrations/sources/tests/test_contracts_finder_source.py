from datetime import date

from integrations.sources.base import DiscoveryQuery
from integrations.sources.contracts_finder import ContractsFinderSource


class RecordingTransport:
    def __init__(self, response, detail_response=None):
        self.response = response
        self.detail_response = detail_response or {"releases": []}
        self.calls = []

    def post_json(self, *, url, payload, timeout_seconds, max_response_bytes):
        self.calls.append({
            "url": url,
            "payload": payload,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
        })
        return self.response

    def get_json(self, *, url, timeout_seconds, max_response_bytes):
        self.calls.append({
            "url": url,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
        })
        return self.detail_response


def _hit(**overrides):
    item = {
        "id": "33764cb5-6f94-41a8-a78e-36f006b8e339",
        "parentId": None,
        "noticeIdentifier": "GEARS-2026",
        "title": "Industrial &amp; marine gears",
        "description": "Supply of replacement gear units",
        "cpvDescription": "Gears and gearing",
        "cpvDescriptionExpanded": "Machinery for the production and use of mechanical power",
        "publishedDate": "2026-08-14T16:35:45+01:00",
        "deadlineDate": "2026-09-07T12:00:00+01:00",
        "awardedDate": None,
        "awardedValue": None,
        "awardedSupplier": None,
        "approachMarketDate": None,
        "valueLow": 0,
        "valueHigh": 20000,
        "postcode": "OX14 3DB",
        "coordinates": "0,0",
        "isSubNotice": False,
        "noticeType": "Contract",
        "noticeStatus": "Open",
        "isSuitableForSme": True,
        "isSuitableForVco": False,
        "awardedToSme": False,
        "awardedToVcse": False,
        "lastNotifableUpdate": "2026-08-14T16:35:45+01:00",
        "organisationName": "Example Contracting Authority",
        "sector": "Public sector",
        "cpvCodes": "42140000 42141300",
        "cpvCodesExtended": "42000000 42100000",
        "region": "South East",
        "regionText": "South East",
        "start": "2026-10-01T00:00:00+01:00",
        "end": "2027-09-30T23:59:59+01:00",
        **overrides,
    }
    return {"score": 1.0, "item": item}


def test_contracts_finder_normalizes_exact_gear_notice_and_uses_bounded_query():
    transport = RecordingTransport(
        {
            "hitCount": 1,
            "noticeList": [_hit()],
            "maxHits": 10,
            "byRegion": {"items": [], "other": 0},
            "byType": {"items": [], "other": 0},
            "byStatus": {"items": [], "other": 0},
        },
        detail_response={
            "releases": [{
                "id": "release-1",
                "buyer": {
                    "id": "GB-CFS-326245",
                    "name": "Example Contracting Authority",
                },
                "parties": [{
                    "id": "GB-CFS-326245",
                    "name": "Example Contracting Authority",
                    "contactPoint": {
                        "name": "Must not be stored",
                        "email": "must-not-be-stored@example.invalid",
                        "telephone": "+44 0000 000000",
                    },
                    "roles": ["buyer"],
                }],
            }],
        },
    )

    batch = ContractsFinderSource(transport=transport).fetch(DiscoveryQuery(
        cpv_codes=("42141300", "42142000"),
        published_from=date(2026, 8, 1),
        limit=10,
    ))

    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.source_code == "UK_CONTRACTS_FINDER"
    assert item.external_id == "33764cb5-6f94-41a8-a78e-36f006b8e339"
    assert item.buyer_identifier == "GB-CFS-326245"
    assert item.buyer_name == "Example Contracting Authority"
    assert item.buyer_country == "GBR"
    assert item.title == "Industrial & marine gears"
    assert item.cpv_codes == ("42140000", "42141300")
    assert item.source_url == (
        "https://www.contractsfinder.service.gov.uk/Notice/"
        "33764cb5-6f94-41a8-a78e-36f006b8e339"
    )
    assert item.deadline_at is not None
    assert batch.capability_snapshot == {
        "source": "UK_CONTRACTS_FINDER",
        "capture_method": "OFFICIAL_PUBLIC_API",
        "authentication": "ANONYMOUS",
        "result_limit": 10,
        "governance": {
            "source_owner": "UK Cabinet Office",
            "access_method": "OFFICIAL_PUBLIC_API",
            "license_contract": "OPEN_GOVERNMENT_LICENCE_3.0",
            "robots_policy": "API_NOT_WEB_SCRAPING",
            "rate_limit": "MAX_20_RESULTS_PER_RUN_DAILY_SCHEDULE",
            "allowed_fields": [
                "buyer_identifier", "buyer_name", "buyer_country", "notice_title",
                "publication_date", "deadline_date", "cpv_codes", "source_url",
            ],
            "retention_period": "365_DAYS_THEN_REVIEW",
            "redistribution_restriction": "SOURCE_LINK_AND_SHORT_EXCERPT_ONLY",
            "queue": "MONITORING",
        },
    }
    search_call, detail_call = transport.calls
    assert search_call["url"] == (
        "https://www.contractsfinder.service.gov.uk/"
        "api/rest/2/search_notices/json"
    )
    assert search_call["timeout_seconds"] == 15
    assert search_call["max_response_bytes"] == 2_000_000
    assert search_call["payload"] == {
        "searchCriteria": {
            "statuses": ["Open"],
            "cpvCodes": ["42141300", "42142000"],
            "publishedFrom": "2026-08-01T00:00:00Z",
        },
        "size": 10,
    }
    assert detail_call == {
        "url": (
            "https://www.contractsfinder.service.gov.uk/Published/Notice/releases/"
            "33764cb5-6f94-41a8-a78e-36f006b8e339.json"
        ),
        "timeout_seconds": 15,
        "max_response_bytes": 2_000_000,
    }
    assert "contact" not in item.__dict__


def test_contracts_finder_skips_parent_only_unsafe_and_incomplete_records():
    transport = RecordingTransport({
        "hitCount": 4,
        "noticeList": [
            _hit(cpvCodes="42000000"),
            _hit(id="../../private"),
            _hit(id="8dad0e31-4a7a-4a24-a1c3-c55bc66fffd0", organisationName=""),
            {"score": 1.0, "item": None},
        ],
        "maxHits": 20,
        "byRegion": {"items": [], "other": 0},
        "byType": {"items": [], "other": 0},
        "byStatus": {"items": [], "other": 0},
    })

    batch = ContractsFinderSource(transport=transport).fetch(DiscoveryQuery(
        cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=20,
    ))

    assert batch.items == ()
    assert batch.skipped_count == 4
    assert batch.total_count == 4
