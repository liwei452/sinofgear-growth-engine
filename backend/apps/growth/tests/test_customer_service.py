import pytest
from decimal import Decimal

from apps.catalog.models import Product
from apps.growth.agent.customer_service_tools import run_customer_service_agent
from apps.growth.customer_service import product_knowledge
from apps.growth.inbound_rfq import record_inbound_rfq
from apps.growth.models import AgentRun, CustomerServiceTurn
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Customer service", slug="customer-service")


def test_customer_service_agent_auto_replies_with_email(organization):
    rfq = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="",
        product_interest="",
    )
    result = run_customer_service_agent(organization=organization, rfq_id=rfq["rfq_id"])

    assert result.status == "completed"
    turn = CustomerServiceTurn.objects.get(organization=organization, rfq_id=rfq["rfq_id"])
    assert turn.decision == CustomerServiceTurn.Decision.AUTO_REPLY
    assert turn.draft_reply


def test_customer_service_agent_escalates_without_email(organization):
    rfq = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="",
        message="Need a gearbox.",
        product_interest="gearbox",
    )
    result = run_customer_service_agent(organization=organization, rfq_id=rfq["rfq_id"])

    assert result.status == "completed"
    turn = CustomerServiceTurn.objects.get(organization=organization, rfq_id=rfq["rfq_id"])
    assert turn.decision == CustomerServiceTurn.Decision.HUMAN_ESCALATION
    assert turn.draft_reply == ""


def test_customer_service_agent_is_idempotent(organization):
    rfq = record_inbound_rfq(
        organization=organization,
        company_name="ABC Mining",
        email="procurement@abc.example",
        message="Need a gearbox.",
        product_interest="gearbox",
    )
    run_customer_service_agent(organization=organization, rfq_id=rfq["rfq_id"])
    run_customer_service_agent(organization=organization, rfq_id=rfq["rfq_id"])

    assert CustomerServiceTurn.objects.filter(rfq_id=rfq["rfq_id"]).count() == 1
    run = AgentRun.objects.get(
        organization=organization,
        idempotency_key=f"customer-service:{rfq['rfq_id']}",
    )
    assert run.steps.count() == 4


def test_product_knowledge_queries_catalog(organization):
    Product.objects.create(
        organization=organization,
        name_en="Industrial Gearbox",
        module_min=Decimal("0.5"),
        module_max=Decimal("4"),
        tooth_count_min=12,
        tooth_count_max=200,
        pressure_angle=Decimal("20"),
        moq=10,
        lead_time="2 weeks",
        manufacturing_capabilities=["gear hobbing", "grinding"],
        inspection_capabilities=["dimensional inspection"],
        status=Product.Status.ACTIVE,
    )
    knowledge = product_knowledge(organization, "gearbox")
    assert "Industrial Gearbox" in knowledge
