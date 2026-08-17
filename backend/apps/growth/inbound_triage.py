"""Route inbound leads to acquisition or customer service."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .growth_events import EVENT_LEAD_ROUTED, emit_growth_event
from .models import InboundLead


def inbound_evidence(account) -> dict:
    signal = (
        account.intent_signals.filter(signal_type="INBOUND_RFQ")
        .order_by("-observed_at", "-id")
        .first()
    )
    envelope = (signal.evidence_envelope or {}) if signal else {}
    email = str(envelope.get("email", "")).strip()
    product_interest = str(envelope.get("product_interest", "")).strip()
    need_slug = str(envelope.get("need_slug", "")).strip()
    message = str(signal.evidence_text or "").strip() if signal else ""
    return {
        "has_email": bool(email and "@" in email),
        "email": email,
        "has_need": bool(product_interest or message) and need_slug not in ("", "unknown"),
        "need_slug": need_slug,
        "product_interest": product_interest,
    }


def decide_inbound_route(evidence: dict) -> str:
    if evidence["has_email"] and evidence["has_need"]:
        return InboundLead.Route.ACQUISITION
    return InboundLead.Route.CUSTOMER_SERVICE


def _route_reason(route: str, evidence: dict) -> str:
    if route == InboundLead.Route.ACQUISITION:
        return "Contactable email and clear need; route to proactive acquisition."
    if route == InboundLead.Route.CUSTOMER_SERVICE:
        return "Needs a conversation to qualify contact or need; route to customer service."
    return "No account to route; manual review required."


@transaction.atomic
def triage_inbound_lead(*, lead: InboundLead) -> InboundLead:
    if lead.account is None:
        lead.route = InboundLead.Route.MANUAL_REVIEW
        lead.route_reason = _route_reason(InboundLead.Route.MANUAL_REVIEW, {})
    else:
        evidence = inbound_evidence(lead.account)
        route = decide_inbound_route(evidence)
        lead.route = route
        lead.route_reason = _route_reason(route, evidence)
    lead.routed_at = timezone.now()
    lead.save(update_fields=["route", "route_reason", "routed_at", "updated_at"])
    emit_growth_event(
        organization=lead.organization,
        event_type=EVENT_LEAD_ROUTED,
        entity_type="lead",
        entity_id=lead.id,
        payload={"route": lead.route, "route_reason": lead.route_reason},
        idempotency_key=f"lead.routed:{lead.id}",
    )
    return lead
