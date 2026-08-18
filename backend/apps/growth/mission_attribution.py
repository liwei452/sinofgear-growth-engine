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


def _linked_receipt_ids(mission: GrowthMission):
    return set(
        MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=MissionEntityLink.EntityType.METRIC_RECEIPT,
        ).values_list("entity_id", flat=True)
    )


def build_mission_attribution(*, mission: GrowthMission) -> dict:
    account_ids = _linked_account_ids(mission)
    receipt_ids = _linked_receipt_ids(mission)
    email_connected = email_delivery_readiness() == "CONNECTED"

    replies = OutreachMessage.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
        status=OutreachMessage.Status.REPLIED,
    )
    rfqs = InboundRfq.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
    )
    won_deals = SalesDeal.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
        stage=SalesDeal.Stage.WON,
    )
    sent = OutreachMessage.objects.filter(
        organization=mission.organization,
        account_id__in=account_ids,
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
    for reply in replies:
        traces.append({
            "confidence": "CONFIRMED",
            "type": "email_reply",
            "source_id": str(reply.id),
        })
    for rfq in rfqs:
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

    return {
        "outcomes": {
            "emails_sent": sent.count() if email_connected else None,
            "confirmed_replies": replies.count(),
            "confirmed_rfqs": rfqs.count(),
            "won_revenue": {"amount": f"{won_total:.2f}"},
            "cost_per_result": None,
        },
        "diagnostics": {"impressions": impressions},
        "availability": {
            "email": "CONNECTED" if email_connected else "NOT_CONNECTED",
        },
        "traces": traces,
    }
