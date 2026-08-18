"""Delivery-state transitions for sent, reply, bounce, and unsubscribe events."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .email_delivery import (
    EmailDeliveryUnavailable,
    email_delivery_readiness,
    get_delivery_provider,
)
from .growth_events import (
    EVENT_EMAIL_BOUNCED,
    EVENT_EMAIL_FAILED,
    EVENT_EMAIL_REPLIED,
    EVENT_EMAIL_SENT,
    EVENT_EMAIL_UNSUBSCRIBED,
    emit_growth_event,
)
from .models import FollowUp, OutreachMessage
from .outreach_stages import transition_stage


@transaction.atomic
def record_sent(*, account, draft, email: str) -> OutreachMessage:
    if email_delivery_readiness() != "CONNECTED":
        raise EmailDeliveryUnavailable("Email delivery is not connected.")
    result = get_delivery_provider().send(
        email=email,
        subject="",
        body=draft.english_draft if draft else "",
    )
    status = str(result.get("status", "SENT"))
    message_id = str(result.get("message_id", "") or "")
    sent = status == "SENT" and bool(message_id)
    message = OutreachMessage.objects.create(
        organization=account.organization,
        account=account,
        draft=draft,
        provider=result.get("provider", "unknown"),
        provider_message_id=message_id,
        status=OutreachMessage.Status.SENT if sent else OutreachMessage.Status.FAILED,
        payload=result,
        sent_at=timezone.now() if sent else None,
    )
    if not sent:
        emit_growth_event(
            organization=account.organization,
            event_type=EVENT_EMAIL_FAILED,
            entity_type="account",
            entity_id=account.id,
            payload={"message_id": str(message.id), "provider": message.provider, "email": email},
            idempotency_key=f"email.failed:{message.id}",
        )
        return message
    follow_up = FollowUp.objects.filter(
        organization=account.organization,
        account=account,
    ).first()
    if follow_up is not None:
        transition_stage(follow_up, "EMAIL_1_SENT")
    emit_growth_event(
        organization=account.organization,
        event_type=EVENT_EMAIL_SENT,
        entity_type="account",
        entity_id=account.id,
        payload={"message_id": str(message.id), "provider": message.provider, "email": email},
        idempotency_key=f"email.sent:{message.id}",
    )
    return message


@transaction.atomic
def record_reply(*, account) -> FollowUp:
    message = account.outreach_messages.order_by("-created_at", "-id").first()
    if message is not None:
        message.status = OutreachMessage.Status.REPLIED
        message.replied_at = timezone.now()
        message.save(update_fields=["status", "replied_at", "updated_at"])
        emit_growth_event(
            organization=account.organization,
            event_type=EVENT_EMAIL_REPLIED,
            entity_type="account",
            entity_id=account.id,
            payload={"message_id": str(message.id)},
            idempotency_key=f"email.replied:{message.id}",
        )
    follow_up = FollowUp.objects.get(organization=account.organization, account=account)
    transition_stage(follow_up, "REPLIED")
    return follow_up


@transaction.atomic
def record_bounce(*, account) -> FollowUp:
    message = account.outreach_messages.order_by("-created_at", "-id").first()
    if message is not None:
        message.status = OutreachMessage.Status.BOUNCED
        message.bounced_at = timezone.now()
        message.save(update_fields=["status", "bounced_at", "updated_at"])
        emit_growth_event(
            organization=account.organization,
            event_type=EVENT_EMAIL_BOUNCED,
            entity_type="account",
            entity_id=account.id,
            payload={"message_id": str(message.id)},
            idempotency_key=f"email.bounced:{message.id}",
        )
    follow_up = FollowUp.objects.get(organization=account.organization, account=account)
    transition_stage(follow_up, "BOUNCED")
    return follow_up


@transaction.atomic
def record_unsubscribe(*, account) -> FollowUp:
    message = account.outreach_messages.order_by("-created_at", "-id").first()
    if message is not None:
        message.status = OutreachMessage.Status.UNSUBSCRIBED
        message.unsubscribed_at = timezone.now()
        message.save(update_fields=["status", "unsubscribed_at", "updated_at"])
        emit_growth_event(
            organization=account.organization,
            event_type=EVENT_EMAIL_UNSUBSCRIBED,
            entity_type="account",
            entity_id=account.id,
            payload={"message_id": str(message.id)},
            idempotency_key=f"email.unsubscribed:{message.id}",
        )
    follow_up = FollowUp.objects.get(organization=account.organization, account=account)
    transition_stage(follow_up, "UNSUBSCRIBED")
    return follow_up
