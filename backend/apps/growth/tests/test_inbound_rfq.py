import pytest
import hashlib
import hmac
import json
import time

from apps.growth.inbound_rfq import record_inbound_rfq, resolve_website_organization
from apps.growth.webhook_auth import verify_webhook_signature
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


def test_inbound_rfq_request_id_is_idempotent(organization):
    first = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need gear.",
        product_interest="gearbox",
        request_id="req-1",
    )
    second = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need gear.",
        product_interest="gearbox",
        request_id="req-1",
    )
    assert first["rfq_id"] == second["rfq_id"]
    assert InboundRfq.objects.filter(organization=organization).count() == 1


def test_webhook_signature_verification():
    payload = {"company_name": "ABC Mining"}
    timestamp = str(int(time.time()))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        "secret".encode(), f"{timestamp}.{canonical}".encode(), hashlib.sha256,
    ).hexdigest()

    assert verify_webhook_signature(
        secret="secret", timestamp=timestamp, signature=signature, payload=payload,
    )
    assert not verify_webhook_signature(
        secret="secret", timestamp=timestamp, signature="bad", payload=payload,
    )
    stale = str(int(time.time()) - 1000)
    stale_signature = hmac.new(
        "secret".encode(), f"{stale}.{canonical}".encode(), hashlib.sha256,
    ).hexdigest()
    assert not verify_webhook_signature(
        secret="secret", timestamp=stale, signature=stale_signature, payload=payload,
    )


def test_resolve_website_organization_rejects_non_uuid():
    assert resolve_website_organization("not-a-uuid") is None


def test_rfq_webhook_requires_hmac(db, settings, monkeypatch):
    from rest_framework.test import APIClient

    from apps.growth import views

    settings.RFQ_WEBHOOK_SECRET = "rfq-secret"
    settings.LEAD_WEBSITE_ORGANIZATION_SLUG = "rfq-org"
    Organization.objects.create(name="RFQ Org", slug="rfq-org")
    monkeypatch.setattr(views, "_webhook_rate_limited", lambda *args, **kwargs: False)

    client = APIClient()
    url = "/api/v1/growth/inbound-rfq"
    payload = {"company_name": "ABC Mining", "email": "p@x.com", "message": "Need gear"}

    bad = client.post(
        url, payload, format="json", HTTP_X_TIMESTAMP="0", HTTP_X_SIGNATURE="bad",
    )
    assert bad.status_code == 403

    timestamp = str(int(time.time()))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(
        "rfq-secret".encode(), f"{timestamp}.{canonical}".encode(), hashlib.sha256,
    ).hexdigest()
    good = client.post(
        url, payload, format="json",
        HTTP_X_TIMESTAMP=timestamp, HTTP_X_SIGNATURE=signature,
    )
    assert good.status_code == 201
    assert good.data["rfq_id"]
