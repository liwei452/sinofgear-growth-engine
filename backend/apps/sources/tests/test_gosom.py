import httpx

from apps.sources.authenticity import SourceAuthenticity, SourceCapability
from apps.sources.adapters.gosom import GosomGoogleMapsAdapter
from apps.sources.registry import SourceRegistry


def _gosom_client(entries):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/scrape":
            return httpx.Response(202, json={"job_id": "job-1", "status": "pending"})
        if request.url.path == "/api/v1/jobs/job-1":
            return httpx.Response(
                200,
                json={"job_id": "job-1", "status": "completed", "results": entries},
            )
        return httpx.Response(404, json={"message": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://gosom")


def test_gosom_adapter_maps_entry_to_real_source_record():
    client = _gosom_client([
        {
            "title": "Acme Mining",
            "address": "12 Industrial Rd",
            "web_site": "https://acme.example",
            "phone": "+49 000 000",
            "latitude": 51.0,
            "longitude": 9.0,
            "review_rating": 4.5,
            "review_count": 12,
            "categories": ["mining equipment"],
            "place_id": "place-1",
            "link": "https://maps.google.com/place-1",
            "complete_address": {"country": "DE"},
        }
    ])
    adapter = GosomGoogleMapsAdapter(client=client)

    records = list(adapter.search("mining equipment in Germany"))

    assert len(records) == 1
    record = records[0]
    assert record.authenticity is SourceAuthenticity.REAL
    assert record.capability is SourceCapability.DISCOVER
    assert record.payload["company_name"] == "Acme Mining"
    assert record.payload["website"] == "https://acme.example"
    assert record.payload["latitude"] == 51.0
    assert record.evidence["source_url"] == "https://maps.google.com/place-1"


def test_registry_accepts_gosom_as_real_discover_source():
    adapter = GosomGoogleMapsAdapter(client=_gosom_client([]))
    registry = SourceRegistry()
    registry.register(adapter)

    assert registry.get("gosom-google-maps") is adapter
    assert [source.id for source in registry.for_capability(SourceCapability.DISCOVER)] == [
        "gosom-google-maps"
    ]
    assert [source.id for source in registry.real_only()] == ["gosom-google-maps"]
