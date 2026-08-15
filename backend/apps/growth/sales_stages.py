from django.utils import timezone

from .models import SalesDeal


DEAL_STAGE_ORDER = ("QUOTE_CREATED", "QUOTE_SENT", "NEGOTIATING", "WON", "LOST", "NURTURE")

DEAL_STAGE_LABELS_ZH = {
    "QUOTE_CREATED": "已创建报价",
    "QUOTE_SENT": "报价已发出",
    "NEGOTIATING": "谈判中",
    "WON": "已成交",
    "LOST": "已流失",
    "NURTURE": "长期培育",
}


def transition_deal_stage(deal: SalesDeal, stage: str) -> SalesDeal:
    if stage not in DEAL_STAGE_ORDER:
        raise ValueError(f"Unknown deal stage: {stage}")
    deal.stage = stage
    if stage == SalesDeal.Stage.WON:
        deal.won_at = timezone.now()
    elif stage == SalesDeal.Stage.LOST:
        deal.lost_at = timezone.now()
    deal.save(update_fields=["stage", "won_at", "lost_at", "updated_at"])
    return deal


def record_learning_feedback(deal: SalesDeal, feedback: str) -> SalesDeal:
    deal.feedback = feedback
    deal.save(update_fields=["feedback", "updated_at"])
    return deal
