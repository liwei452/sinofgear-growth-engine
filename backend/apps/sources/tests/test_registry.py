import pytest

from apps.sources.authenticity import SourceAuthenticity, SourceCapability
from apps.sources.record import SourceRecord
from apps.sources.registry import SourceRegistry


class _RealDiscoverSource:
    id = "openstreetmap"
    category = "local"
    capability = SourceCapability.DISCOVER
    authenticity = SourceAuthenticity.REAL
    requires_api_key = False
    rate_limit = 60
    enabled = True

    def search(self, query, options=None):
        yield SourceRecord(
            source=self.id,
            capability=self.capability,
            authenticity=self.authenticity,
            confidence=0.8,
            evidence={"source_url": "https://nominatim.openstreetmap.org/search"},
            payload={"company_name": "Acme"},
        )


class _SyntheticSource:
    id = "fake-maps"
    category = "local"
    capability = SourceCapability.DISCOVER
    authenticity = SourceAuthenticity.SYNTHETIC
    requires_api_key = False
    rate_limit = 60
    enabled = True

    def search(self, query, options=None):
        return iter(())


def test_synthetic_source_cannot_be_registered():
    registry = SourceRegistry()
    with pytest.raises(ValueError, match="SYNTHETIC"):
        registry.register(_SyntheticSource())


def test_real_source_registers_and_is_queryable_by_capability():
    registry = SourceRegistry()
    registry.register(_RealDiscoverSource())

    assert registry.get("openstreetmap").authenticity is SourceAuthenticity.REAL
    assert [source.id for source in registry.for_capability(SourceCapability.DISCOVER)] == [
        "openstreetmap"
    ]
    assert [source.id for source in registry.real_only()] == ["openstreetmap"]


def test_source_record_rejects_invalid_confidence():
    with pytest.raises(ValueError, match="confidence"):
        SourceRecord(
            source="x",
            capability=SourceCapability.DISCOVER,
            authenticity=SourceAuthenticity.REAL,
            confidence=1.5,
        )


def test_source_record_rejects_synthetic():
    with pytest.raises(ValueError, match="SYNTHETIC"):
        SourceRecord(
            source="x",
            capability=SourceCapability.DISCOVER,
            authenticity=SourceAuthenticity.SYNTHETIC,
            confidence=0.5,
        )
