"""Delivery-state transitions for sent, reply, bounce, and unsubscribe events."""

from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone
from apps.common.tenancy import tenant_atomic

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


EMAIL_SUBJECT = "Technical capability review"
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def record_sent(
    *, account, draft, email: str, organization_id=None
) -> OutreachMessage:
    normalized_email = email.strip().lower()
    context_id = organization_id
    def context():
        return (
            tenant_atomic(context_id)
            if context_id is not None
            else transaction.atomic()
        )
    with context():
        accounts = type(account).objects.select_for_update()
        if context_id is not None:
            accounts = accounts.filter(organization_id=context_id)
        locked_account = accounts.get(pk=account.pk)
        locked_draft = None
        if draft is not None:
            drafts = type(draft).objects.select_for_update()
            if context_id is not None:
                drafts = drafts.filter(organization_id=context_id)
            locked_draft = drafts.get(pk=draft.pk, account=locked_account)
        if email_delivery_readiness() != "CONNECTED":
            raise EmailDeliveryUnavailable("Email delivery is not connected.")
        body = locked_draft.english_draft if locked_draft else ""
        if locked_draft and locked_draft.knowledge_context_snapshot_id:
            from apps.knowledge.agent_context import (
                AgentContextPurpose,
                load_agent_context,
                validate_external_output,
            )

            snapshot = locked_draft.knowledge_context_snapshot
            context_view = load_agent_context(
                organization=locked_account.organization,
                mission=snapshot.mission,
                snapshot_id=snapshot.id,
            ).for_purpose(AgentContextPurpose.OUTREACH)
            validate_external_output(
                {
                    "subject": EMAIL_SUBJECT,
                    "draft": body,
                    "cited_fact_ids": _UUID_PATTERN.findall(
                        locked_draft.chinese_explanation
                    ),
                },
                context=context_view,
            )
    result = get_delivery_provider().send(
        email=normalized_email,
        subject=EMAIL_SUBJECT,
        body=body,
    )
    with context():
        accounts = type(account).objects.select_for_update()
        if context_id is not None:
            accounts = accounts.filter(organization_id=context_id)
        account = accounts.get(pk=account.pk)
        if draft is not None:
            drafts = type(draft).objects.select_for_update()
            if context_id is not None:
                drafts = drafts.filter(organization_id=context_id)
            draft = drafts.get(pk=draft.pk, account=account)
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
            payload={**result, "email": normalized_email},
            sent_at=timezone.now() if sent else None,
        )
        if not sent:
            emit_growth_event(
                organization=account.organization,
                event_type=EVENT_EMAIL_FAILED,
                entity_type="account",
                entity_id=account.id,
                payload={
                    "message_id": str(message.id),
                    "provider": message.provider,
                    "email": normalized_email,
                },
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
            payload={
                "message_id": str(message.id),
                "provider": message.provider,
                "email": normalized_email,
            },
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
