import pytest

from apps.growth.inbound_rfq import record_inbound_rfq, resolve_website_organization
from apps.growth.models import (
    Contact,
    DiscoveryCandidate,
    FollowUp,
    InboundLead,
    IntentSignal,
    TargetAccount,
)
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Inbound RFQ", slug="inbound-rfq")


def test_record_inbound_rfq_creates_lead_chain(organization):
    result = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a replacement helical gear for an existing gearbox.",
        product_interest="replacement-gears",
    )
    assert result["need_slug"] == "replacement"
    account = TargetAccount.objects.get(organization=organization)
    assert account.name == "ABC Mining"
    assert IntentSignal.objects.filter(account=account, signal_type="INBOUND_RFQ").exists()
    assert FollowUp.objects.filter(account=account).exists()
    assert InboundLead.objects.filter(account=account).exists()
    assert Contact.objects.filter(account=account).exists()


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
