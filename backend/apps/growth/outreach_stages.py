from .models import FollowUp


STAGE_ORDER = (
    "DISCOVERED", "QUALIFIED", "ENRICHED", "CONTACT_FOUND", "EMAIL_VERIFIED",
    "OUTREACH_READY", "EMAIL_1_SENT", "OPENED", "SITE_VISITED", "FOLLOW_UP_1",
    "REPLIED", "RFQ", "QUOTED", "WON", "LOST",
)

STAGE_LABELS_ZH = {
    "DISCOVERED": "已发现",
    "QUALIFIED": "已初步判断",
    "ENRICHED": "已补全情报",
    "CONTACT_FOUND": "已找到联系人",
    "EMAIL_VERIFIED": "邮箱已验证",
    "OUTREACH_READY": "可触达",
    "EMAIL_1_SENT": "已发第一封",
    "OPENED": "已打开",
    "SITE_VISITED": "已访问官网",
    "FOLLOW_UP_1": "已跟进一次",
    "REPLIED": "已回复",
    "RFQ": "已收到询盘",
    "QUOTED": "已报价",
    "WON": "已成交",
    "LOST": "已流失",
}


def transition_stage(follow_up: FollowUp, stage: str) -> FollowUp:
    if stage not in STAGE_ORDER:
        raise ValueError(f"Unknown outreach stage: {stage}")
    follow_up.stage = stage
    follow_up.save(update_fields=["stage", "updated_at"])
    return follow_up
