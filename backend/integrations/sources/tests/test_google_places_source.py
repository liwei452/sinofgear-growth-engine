from integrations.sources.base import maps_governance_for
from integrations.sources.google_places import (
    GooglePlacesSource,
    MapsBatch,
    MapsQuery,
)


class FakeGooglePlacesTransport:
    def __init__(self, response: dict):
        self.response = response
        self.calls = []

    def post_json(
        self,
        *,
        url: str,
        payload: dict,
        api_key: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict:
        self.calls.append({
            "url": url,
            "payload": payload,
            "api_key": api_key,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
        })
        return self.response


def _sample_response() -> dict:
    return {
        "places": [
            {
                "id": "ChIJ_sample_1",
                "displayName": {"text": "PT Mitra Engineering"},
                "formattedAddress": "Jl. Industri, Jakarta, Indonesia",
                "websiteUri": "https://mitra.example",
                "primaryType": "industrial_supplier",
                "types": ["industrial_supplier", "point_of_interest"],
                "nationalPhoneNumber": "021-555-0100",
            },
            {
                "id": "ChIJ_sample_2",
                "displayName": {"text": "ConveyorWorks SA"},
                "formattedAddress": "Johannesburg, South Africa",
                "primaryType": "general_contractor",
                "types": ["general_contractor"],
            },
            {"id": "ChIJ_sample_3"},  # missing name -> skipped
        ]
    }


def test_fetch_normalizes_places_and_passes_api_key():
    transport = FakeGooglePlacesTransport(_sample_response())
    source = GooglePlacesSource(api_key="test-key", transport=transport)

    batch = source.fetch(MapsQuery(text_query="industrial machinery Jakarta", region_code="ID", limit=20))

    assert isinstance(batch, MapsBatch)
    assert len(batch.places) == 2
    assert batch.skipped_count == 1
    first = batch.places[0]
    assert first.place_id == "ChIJ_sample_1"
    assert first.name == "PT Mitra Engineering"
    assert first.website == "https://mitra.example"
    assert first.phone == "021-555-0100"
    assert first.country_code == "ID"
    assert first.source_url.endswith("place_id:ChIJ_sample_1")

    call = transport.calls[0]
    assert call["api_key"] == "test-key"
    assert call["payload"]["textQuery"] == "industrial machinery Jakarta"
    assert call["payload"]["regionCode"] == "ID"
    assert call["url"].endswith("/v1/places:searchText")


def test_governance_reflects_google_caching_rules():
    governance = maps_governance_for("GOOGLE_MAPS")
    assert governance["robots_policy"] == "API_NOT_WEB_SCRAPING"
    assert governance["retention_period"] == "PLACE_ID_INDEFINITE_OTHER_FIELDS_30_DAYS"
    assert "place_id" in governance["allowed_fields"]


def test_invalid_query_and_missing_key_are_rejected():
    try:
        MapsQuery(text_query="", region_code="ID")
    except ValueError:
        pass
    else:
        raise AssertionError("expected empty text query to be rejected")

    try:
        MapsQuery(text_query="gears", region_code="IDN")
    except ValueError:
        pass
    else:
        raise AssertionError("expected invalid region code to be rejected")

    try:
        GooglePlacesSource(api_key="", transport=FakeGooglePlacesTransport({}))
    except ValueError:
        pass
    else:
        raise AssertionError("expected empty api key to be rejected")
