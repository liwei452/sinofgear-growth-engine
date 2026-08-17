import pytest

from apps.growth.inbound_rfq import record_inbound_rfq, resolve_website_organization
from apps.growth.inbound_triage import decide_inbound_route, triage_inbound_lead
from apps.growth.models import (
    Contact,
    DiscoveryCandidate,
    FollowUp,
    InboundLead,
    InboundRfq,
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
    lead = InboundLead.objects.get(account=account)
    assert lead.route == InboundLead.Route.ACQUISITION
    assert lead.routed_at is not None
    assert Contact.objects.filter(account=account).exists()
    assert result["route"] == InboundLead.Route.ACQUISITION
    assert InboundRfq.objects.filter(id=result["rfq_id"]).exists()


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


def test_inbound_rfq_without_email_routes_to_customer_service(organization):
    result = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="",
        message="Need a replacement helical gear.",
        product_interest="replacement-gears",
    )
    lead = InboundLead.objects.get(id=result["lead_id"])
    assert lead.route == InboundLead.Route.CUSTOMER_SERVICE


def test_decide_inbound_route(organization):
    assert decide_inbound_route({"has_email": True, "has_need": True}) == InboundLead.Route.ACQUISITION
    assert decide_inbound_route({"has_email": False, "has_need": True}) == InboundLead.Route.CUSTOMER_SERVICE
    assert decide_inbound_route({"has_email": True, "has_need": False}) == InboundLead.Route.CUSTOMER_SERVICE


def test_triage_inbound_lead_without_account_is_manual(organization):
    lead = InboundLead.objects.create(organization=organization, source_label="orphan")
    triage_inbound_lead(lead=lead)
    assert lead.route == InboundLead.Route.MANUAL_REVIEW


def test_inbound_rfq_saves_each_inquiry_separately(organization):
    record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need gear A.",
        product_interest="gearbox",
    )
    record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need gear B.",
        product_interest="gearbox",
    )
    rfqs = list(InboundRfq.objects.filter(organization=organization).order_by("created_at"))
    assert len(rfqs) == 2
    assert rfqs[0].email == "procurement@abc.example"
    assert rfqs[0].contact_name == "Website inquiry"
    assert rfqs[0].message == "Need gear A."
