import pytest

from apps.growth.inbound_rfq import record_inbound_rfq
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
