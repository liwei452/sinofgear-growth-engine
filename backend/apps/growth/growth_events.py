"""Transactional outbox for growth events consumed by the gateway."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import GrowthEvent


EVENT_COMPANY_DISCOVERED = "company.discovered"
EVENT_CONTACT_VERIFIED = "contact.verified"
EVENT_LEAD_ROUTED = "lead.routed"
EVENT_EMAIL_SENT = "email.sent"
EVENT_EMAIL_REPLIED = "email.replied"
EVENT_EMAIL_BOUNCED = "email.bounced"
EVENT_EMAIL_UNSUBSCRIBED = "email.unsubscribed"
EVENT_RFQ_CREATED = "rfq.created"
EVENT_CUSTOMER_SERVICE_DECIDED = "customer_service.decided"


@transaction.atomic
def emit_growth_event(
    *,
    organization,
    event_type: str,
    entity_type: str,
    entity_id,
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> GrowthEvent:
    key = idempotency_key or f"{event_type}:{entity_type}:{entity_id}"
    event, _ = GrowthEvent.objects.get_or_create(
        organization=organization,
        idempotency_key=key,
        defaults={
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "payload": payload or {},
            "occurred_at": timezone.now(),
        },
    )
    return event


def unpublished_growth_events(*, organization, limit: int = 100) -> list[GrowthEvent]:
    return list(
        GrowthEvent.objects.filter(organization=organization, published_at__isnull=True)
        .order_by("occurred_at", "id")[:limit]
    )


@transaction.atomic
def mark_events_published(*, organization, event_ids: list) -> int:
    return GrowthEvent.objects.filter(
        organization=organization,
        id__in=event_ids,
        published_at__isnull=True,
    ).update(published_at=timezone.now())
