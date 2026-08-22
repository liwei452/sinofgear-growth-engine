import pytest
from django.db import connection

from apps.growth.maps_discovery import (
    MapsDiscoveryNotEnabled,
    probe_maps_connection,
    run_maps_discovery,
)
from apps.growth.models import DiscoveryCandidate, GoogleMapsDiscoveryConfig
from apps.identity.models import Organization
from integrations.secrets import decrypt_secret, encrypt_secret
from integrations.sources.google_places import MapsBatch, MapsPlace


class FakeMapsSource:
    def __init__(self, api_key):
        self.api_key = api_key
        self.queries = []

    def fetch(self, query):
        self.queries.append(query)
        place = MapsPlace(
            place_id="ChIJ_maps_1",
            name="PT Mitra Engineering",
            address="Jakarta Industrial Estate",
            website="https://mitra.example",
            phone="021-555-0100",
            primary_type="industrial_supplier",
            types=("industrial_supplier", "point_of_interest"),
            country_code=query.region_code,
            source_url="https://www.google.com/maps/place/?q=place_id:ChIJ_maps_1",
        )
        return MapsBatch(
            places=(place,),
            capability_snapshot={},
            skipped_count=0,
            total_count=1,
            is_demo=False,
        )


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Maps discovery", slug="maps-discovery")


@pytest.fixture
def config(organization):
    return GoogleMapsDiscoveryConfig.objects.create(
        organization=organization,
        enabled=True,
        api_key_ciphertext=encrypt_secret("maps-api-key"),
        cities=[{"name": "Jakarta", "country_code": "ID"}],
        keywords=["conveyor", "crusher"],
        daily_quota=10,
    )


def test_secret_round_trip():
    assert decrypt_secret(encrypt_secret("secret-value")) == "secret-value"


def test_run_maps_discovery_deduplicates_and_records_success(organization, config):
    sources = []

    def factory(api_key):
        source = FakeMapsSource(api_key)
        sources.append(source)
        return source

    result = run_maps_discovery(config.id, trigger="MANUAL", source_factory=factory)

    assert result["fetched_count"] == 2
    assert result["created_count"] == 1
    assert result["duplicate_count"] == 1
    assert sources[0].api_key == "maps-api-key"
    assert len(sources[0].queries) == 2

    candidates = DiscoveryCandidate.objects.filter(organization=organization)
    assert candidates.count() == 1
    candidate = candidates.get()
    assert candidate.company_name == "PT Mitra Engineering"
    assert candidate.import_format == "GOOGLE_MAPS"
    assert candidate.raw_record["place_id"] == "ChIJ_maps_1"
    assert candidate.source_governance["place_id"] == "ChIJ_maps_1"

    config.refresh_from_db()
    assert config.last_succeeded_at is not None
    assert config.consecutive_failures == 0
    assert config.last_error_code == ""


@pytest.mark.django_db(transaction=True)
def test_run_due_maps_configs_scans_only_due_and_enabled(
    organization, config, monkeypatch
):
    from apps.growth.tasks import scan_due_maps_configs

    sources = []

    def factory(api_key):
        source = FakeMapsSource(api_key)
        original_fetch = source.fetch

        def fetch_outside_transaction(query):
            assert connection.in_atomic_block is False
            return original_fetch(query)

        source.fetch = fetch_outside_transaction
        sources.append(source)
        return source

    monkeypatch.setattr(
        "apps.growth.maps_discovery.GooglePlacesSource",
        factory,
    )
    result = scan_due_maps_configs.run(limit=5)
    assert result["scanned"] == 1
    assert result["succeeded"] == 1
    assert DiscoveryCandidate.objects.filter(organization=organization).count() == 1


def test_disabled_config_is_rejected(organization, config):
    config.enabled = False
    config.save(update_fields=["enabled"])
    with pytest.raises(MapsDiscoveryNotEnabled):
        run_maps_discovery(config.id, trigger="MANUAL", source_factory=lambda key: FakeMapsSource(key))


def test_maps_connection_ok_with_fake_source(config):
    result = probe_maps_connection(config.id, source_factory=lambda key: FakeMapsSource(key))
    assert result["ok"] is True


def test_maps_connection_requires_key(organization):
    empty = GoogleMapsDiscoveryConfig.objects.create(
        organization=organization,
        enabled=True,
        api_key_ciphertext="",
    )
    result = probe_maps_connection(empty.id)
    assert result["ok"] is False
    assert result["error_code"] == "API_KEY_NOT_CONFIGURED"
