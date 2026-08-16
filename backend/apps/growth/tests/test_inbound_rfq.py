import pytest

from apps.growth.inbound_rfq import record_inbound_rfq, resolve_website_organization
from apps.growth.models import DiscoveryCandidate
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Inbound RFQ", slug="inbound-rfq")


def test_record_inbound_rfq_classifies_need(organization):
    rfq = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a replacement helical gear for an existing gearbox.",
        product_interest="replacement-gears",
    )
    assert rfq.need_slug == "replacement"
    assert rfq.company_name == "ABC Mining"


def test_resolve_website_organization_from_lead_id(organization):
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="ABC Mining",
        country="ZAF",
        import_format="GOOGLE_MAPS",
        record_hash="org-resolve-hash",
    )
    assert resolve_website_organization(str(candidate.id)) == organization


def test_resolve_website_organization_returns_none_without_config(organization):
    assert resolve_website_organization("") is None
