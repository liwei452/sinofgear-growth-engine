import httpx

from apps.sources.adapters.dns_lookup import DnsLookupAdapter
from apps.sources.adapters.openstreetmap import OpenStreetMapAdapter
from apps.sources.adapters.sec_edgar import SECEdgarAdapter
from apps.sources.authenticity import SourceAuthenticity, SourceCapability
from apps.sources.registry import SourceRegistry


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openstreetmap_adapter_maps_nominatim_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "nominatim.openstreetmap.org" in str(request.url)
        return httpx.Response(200, json=[{
            "place_id": 1,
            "lat": "51.0",
            "lon": "9.0",
            "display_name": "Acme Mining, Essen, Germany",
            "type": "industrial",
            "osm_type": "node",
            "osm_id": 123,
            "licence": "ODbL",
            "address": {"country": "Germany"},
        }])

    adapter = OpenStreetMapAdapter(client=_client(handler))
    record = next(adapter.search("mining in Essen"))

    assert record.authenticity is SourceAuthenticity.REAL
    assert record.capability is SourceCapability.DISCOVER
    assert record.payload["company_name"] == "Acme Mining"
    assert record.payload["country"] == "Germany"
    assert record.payload["latitude"] == 51.0


def test_sec_edgar_adapter_maps_company_hit():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "efts.sec.gov" in str(request.url)
        return httpx.Response(200, json={"hits": {"hits": [{"_source": {
            "entity_name": "Acme Corp",
            "entity_type": "company",
            "ciks": ["0000000000"],
            "file_date": "2026-01-01",
            "form_type": "10-K",
        }}]}})

    adapter = SECEdgarAdapter(client=_client(handler))
    record = next(adapter.search("Acme Corp"))

    assert record.authenticity is SourceAuthenticity.REAL
    assert record.capability is SourceCapability.RESEARCH
    assert record.payload["company_name"] == "Acme Corp"
    assert record.payload["external_id"] == "0000000000"


def test_dns_lookup_adapter_reports_mx():
    def handler(request: httpx.Request) -> httpx.Response:
        record_type = request.url.params["type"]
        if record_type == "MX":
            body = {"Status": 0, "Answer": [{"data": "10 alt1.aspmx.l.google.com"}]}
        else:
            body = {"Status": 0, "Answer": [{"data": "142.250.0.1"}]}
        return httpx.Response(200, json=body)

    adapter = DnsLookupAdapter(client=_client(handler))
    record = next(adapter.verify({"email": "buyer@acme.example"}))

    assert record.authenticity is SourceAuthenticity.REAL
    assert record.capability is SourceCapability.VERIFY
    assert record.payload["domain"] == "acme.example"
    assert record.payload["has_mx"] is True
    assert record.payload["email_provider"] == "Google Workspace"


def test_all_real_adapters_register_together():
    registry = SourceRegistry()
    registry.register(OpenStreetMapAdapter(client=_client(lambda _: httpx.Response(200, json=[]))))
    registry.register(SECEdgarAdapter(client=_client(lambda _: httpx.Response(200, json={"hits": {"hits": []}}))))
    registry.register(DnsLookupAdapter(client=_client(lambda _: httpx.Response(200, json={}))))

    assert {source.id for source in registry.all()} == {"openstreetmap", "sec-edgar", "dns-lookup"}
    assert {source.id for source in registry.for_capability(SourceCapability.VERIFY)} == {"dns-lookup"}
