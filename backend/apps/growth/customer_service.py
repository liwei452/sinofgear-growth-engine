"""Customer-service agent helpers for looking up context and drafting replies."""

from __future__ import annotations

import json

from django.db import transaction
from django.db.models import Q

from apps.ai.provider_config import resolve_product_ai
from apps.catalog.models import Product

from .growth_events import EVENT_CUSTOMER_SERVICE_DECIDED, emit_growth_event
from .inbound_triage import inbound_evidence
from .models import CustomerServiceTurn, InboundLead


DEFAULT_KNOWLEDGE = "Industrial gears, transmission parts, and custom manufacturing."

KEYWORD_MAP = {
    "gearbox": ["gearbox", "gear"],
    "replacement": ["replacement", "gear"],
    "gear": ["gear"],
}

REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": ["reply", "reasoning"],
}


def lead_context(lead: InboundLead) -> dict:
    evidence = inbound_evidence(lead.account) if lead.account else {}
    account = lead.account
    return {
        "company_name": account.name if account else "",
        "has_email": bool(evidence.get("has_email")),
        "email": evidence.get("email", ""),
        "need_slug": evidence.get("need_slug", ""),
        "product_interest": evidence.get("product_interest", ""),
    }


def _keywords(need_slug: str) -> list[str]:
    if not need_slug:
        return ["gear"]
    return KEYWORD_MAP.get(need_slug, [need_slug])


def product_knowledge(organization, need_slug: str) -> str:
    query = Q()
    for keyword in _keywords(need_slug):
        query |= Q(name_en__icontains=keyword) | Q(name_zh__icontains=keyword)
    products = list(
        Product.objects.filter(organization=organization, status=Product.Status.ACTIVE)
        .filter(query)
        .order_by("name_en", "id")[:3]
    )
    if not products:
        return DEFAULT_KNOWLEDGE
    return "; ".join(_product_summary(product) for product in products)


def _product_summary(product: Product) -> str:
    name = product.name_en or product.name_zh
    capabilities = ", ".join(product.manufacturing_capabilities[:3]) or "custom manufacturing"
    lead_time = product.lead_time or "confirm"
    return f"{name} (MOQ {product.moq}, lead time {lead_time}, capabilities: {capabilities})"


def draft_reply(organization, context: dict) -> str:
    runtime = resolve_product_ai(organization)
    if runtime.real_requests_enabled:
        return _llm_reply(organization, context, runtime.provider)
    return _template_reply(organization, context)


def _llm_reply(organization, context: dict, provider) -> str:
    knowledge = product_knowledge(organization, context["need_slug"])
    prompt = "Draft a short customer-service reply using only the supplied facts.\n||INPUT:" + json.dumps(
        {"context": context, "knowledge": knowledge},
        ensure_ascii=False,
    )
    try:
        result = provider.generate(prompt=prompt, schema=REPLY_SCHEMA)
        return result["reply"]
    except Exception:
        return _template_reply(organization, context)


def _template_reply(organization, context: dict) -> str:
    knowledge = product_knowledge(organization, context["need_slug"])
    if context["has_email"] and context["need_slug"]:
        interest = context["product_interest"] or context["need_slug"]
        return (
            f"Thanks for reaching out about {interest}. {knowledge} "
            "May I ask about quantity and timeline?"
        )
    if context["has_email"]:
        return "Thanks for reaching out. Could you share which product or application you are looking for?"
    return ""


def decide(context: dict) -> str:
    if not context["has_email"]:
        return CustomerServiceTurn.Decision.HUMAN_ESCALATION
    return CustomerServiceTurn.Decision.AUTO_REPLY


def _reasoning(decision: str, context: dict) -> str:
    if decision == CustomerServiceTurn.Decision.HUMAN_ESCALATION:
        return "No contactable email; a human must obtain or verify contact information."
    return "Contactable email present; a draft clarifying reply can be reviewed."


@transaction.atomic
def record_customer_service_turn(*, lead: InboundLead, rfq) -> CustomerServiceTurn:
    context = lead_context(lead)
    decision = decide(context)
    turn, _ = CustomerServiceTurn.objects.get_or_create(
        organization=lead.organization,
        rfq=rfq,
        defaults={
            "lead": lead,
            "decision": decision,
            "draft_reply": draft_reply(lead.organization, context),
            "reasoning": _reasoning(decision, context),
            "evidence": context,
        },
    )
    emit_growth_event(
        organization=lead.organization,
        event_type=EVENT_CUSTOMER_SERVICE_DECIDED,
        entity_type="lead",
        entity_id=lead.id,
        payload={"decision": turn.decision, "draft_reply": turn.draft_reply},
        idempotency_key=f"customer_service.decided:{rfq.id}",
    )
    return turn
