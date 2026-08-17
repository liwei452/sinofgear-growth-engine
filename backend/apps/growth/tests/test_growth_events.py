import pytest

from apps.growth.agent.customer_service_tools import run_customer_service_agent
from apps.growth.growth_events import (
    emit_growth_event,
    mark_events_published,
    unpublished_growth_events,
)
from apps.growth.inbound_rfq import record_inbound_rfq
from apps.growth.models import (
    FollowUp,
    GrowthEvent,
    InboundLead,
    OutreachDraft,
    TargetAccount,
)
from apps.growth.outreach_events import record_sent
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Growth events", slug="growth-events")


def test_emit_growth_event_is_idempotent(organization):
    emit_growth_event(
        organization=organization,
        event_type="company.discovered",
        entity_type="account",
        entity_id="a1",
        idempotency_key="k1",
    )
    emit_growth_event(
        organization=organization,
        event_type="company.discovered",
        entity_type="account",
        entity_id="a1",
        idempotency_key="k1",
    )
    assert GrowthEvent.objects.filter(organization=organization).count() == 1


def test_unpublished_and_mark_published(organization):
    event = emit_growth_event(
        organization=organization,
        event_type="email.sent",
        entity_type="account",
        entity_id="a1",
        idempotency_key="k2",
    )
    assert len(unpublished_growth_events(organization=organization)) == 1
    mark_events_published(organization=organization, event_ids=[event.id])
    assert len(unpublished_growth_events(organization=organization)) == 0


def test_inbound_rfq_emits_rfq_and_routing_events(organization):
    record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a gear.",
        product_interest="gearbox",
    )
    types = set(
        GrowthEvent.objects.filter(organization=organization).values_list("event_type", flat=True)
    )
    assert "rfq.created" in types
    assert "lead.routed" in types


def test_send_emits_email_sent_event(organization):
    account = TargetAccount.objects.create(organization=organization, name="ABC", country="VN")
    draft = OutreachDraft.objects.create(
        organization=organization,
        account=account,
        english_draft="Hello",
        chinese_explanation="test",
    )
    FollowUp.objects.create(organization=organization, account=account)
    record_sent(account=account, draft=draft, email="a@example.com")
    assert GrowthEvent.objects.filter(
        organization=organization,
        event_type="email.sent",
    ).exists()


def test_customer_service_emits_decision_event(organization):
    rfq = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a gear.",
        product_interest="gearbox",
    )
    lead = InboundLead.objects.get(id=rfq["lead_id"])
    run_customer_service_agent(organization=organization, lead_id=str(lead.id))
    assert GrowthEvent.objects.filter(
        organization=organization,
        event_type="customer_service.decided",
    ).exists()
