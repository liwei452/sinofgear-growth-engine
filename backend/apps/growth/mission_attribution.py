from __future__ import annotations

from django.db.models import Sum

from .email_delivery import email_delivery_readiness
from .models import (
    GrowthMission,
    InboundRfq,
    MetricReceipt,
    MissionEntityLink,
    OutreachMessage,
    SalesDeal,
)


def _linked_account_ids(mission: GrowthMission):
    return set(
        MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=MissionEntityLink.EntityType.TARGET_ACCOUNT,
        ).values_list("entity_id", flat=True)
    )


def _linked_entity_ids(mission: GrowthMission, entity_type):
    return set(
        MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=entity_type,
        ).values_list("entity_id", flat=True)
    )


def build_mission_attribution(*, mission: GrowthMission) -> dict:
    account_ids = _linked_account_ids(mission)
    message_ids = _linked_entity_ids(mission, MissionEntityLink.EntityType.OUTREACH_MESSAGE)
    rfq_ids = _linked_entity_ids(mission, MissionEntityLink.EntityType.INBOUND_RFQ)
    deal_ids = _linked_entity_ids(mission, MissionEntityLink.EntityType.SALES_DEAL)
    receipt_ids = _linked_entity_ids(mission, MissionEntityLink.EntityType.METRIC_RECEIPT)
    email_connected = email_delivery_readiness() == "CONNECTED"

    confirmed_replies = OutreachMessage.objects.filter(
        organization=mission.organization,
        id__in=message_ids,
        status=OutreachMessage.Status.REPLIED,
    )
    confirmed_rfqs = InboundRfq.objects.filter(
        organization=mission.organization,
        id__in=rfq_ids,
    )
    won_deals = SalesDeal.objects.filter(
        organization=mission.organization,
        id__in=deal_ids,
        stage=SalesDeal.Stage.WON,
    )
    sent = OutreachMessage.objects.filter(
        organization=mission.organization,
        id__in=message_ids,
        status=OutreachMessage.Status.SENT,
    )
    receipts = MetricReceipt.objects.filter(
        organization=mission.organization,
        id__in=receipt_ids,
        is_demo=False,
    )

    impressions = 0
    for receipt in receipts:
        value = (receipt.payload or {}).get("impressions")
        if isinstance(value, (int, float)) and value >= 0:
            impressions += int(value)

    won_total = won_deals.aggregate(total=Sum("quote_amount"))["total"] or 0

    traces: list[dict] = []
    for reply in confirmed_replies:
        traces.append({
            "confidence": "CONFIRMED",
            "type": "email_reply",
            "source_id": str(reply.id),
        })
    for rfq in confirmed_rfqs:
        traces.append({
            "confidence": "CONFIRMED",
            "type": "rfq",
            "source_id": str(rfq.id),
        })
    for deal in won_deals:
        traces.append({
            "confidence": "CONFIRMED",
            "type": "won_deal",
            "source_id": str(deal.id),
        })
    for receipt in receipts:
        traces.append({
            "confidence": "ASSISTED",
            "type": "metric_receipt",
            "source_id": str(receipt.id),
        })

    assisted_replies = OutreachMessage.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
        status=OutreachMessage.Status.REPLIED,
    ).exclude(id__in=message_ids)
    assisted_rfqs = InboundRfq.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
    ).exclude(id__in=rfq_ids)
    for reply in assisted_replies:
        traces.append({
            "confidence": "ASSISTED",
            "type": "email_reply",
            "source_id": str(reply.id),
        })
    for rfq in assisted_rfqs:
        traces.append({
            "confidence": "ASSISTED",
            "type": "rfq",
            "source_id": str(rfq.id),
        })

    return {
        "outcomes": {
            "emails_sent": sent.count() if email_connected else None,
            "confirmed_replies": confirmed_replies.count(),
            "confirmed_rfqs": confirmed_rfqs.count(),
            "won_revenue": {"amount": f"{won_total:.2f}"},
            "cost_per_result": None,
        },
        "diagnostics": {"impressions": impressions},
        "availability": {
            "email": "CONNECTED" if email_connected else "NOT_CONNECTED",
        },
        "traces": traces,
    }
