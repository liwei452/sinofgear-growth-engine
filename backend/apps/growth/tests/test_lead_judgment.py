import pytest

from apps.growth.lead_judgment import judge_candidate
from apps.growth.models import DiscoveryCandidate
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Lead judgment", slug="lead-judgment")


def _candidate(organization):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="PT Mitra Engineering",
        country="Vietnam",
        website="https://mitra.example",
        industry="gearbox repair",
        status=DiscoveryCandidate.Status.ACCEPTED,
        import_format="GOOGLE_MAPS",
        raw_record={"primary_type": "industrial_supplier", "types": ["industrial_supplier", "gearbox_repair_shop"]},
        record_hash="judgment-test-hash",
    )


def test_deterministic_judgment_when_no_real_provider(organization):
    candidate = _candidate(organization)
    result = judge_candidate(candidate)
    assert result["grade"] in {"A", "B", "C"}
    assert isinstance(result["score"], int)
    assert result["industry"]
