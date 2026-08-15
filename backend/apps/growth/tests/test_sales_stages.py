import pytest

from apps.growth.models import SalesDeal, TargetAccount
from apps.growth.sales_stages import (
    DEAL_STAGE_LABELS_ZH,
    DEAL_STAGE_ORDER,
    record_learning_feedback,
    transition_deal_stage,
)
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Sales stages", slug="sales-stages")


def test_deal_lifecycle_transitions_and_feedback(organization):
    account = TargetAccount.objects.create(organization=organization, name="ABC Mining", country="ZAF")
    deal = SalesDeal.objects.create(organization=organization, account=account)

    assert deal.stage == SalesDeal.Stage.QUOTE_CREATED

    transition_deal_stage(deal, "NEGOTIATING")
    deal.refresh_from_db()
    assert deal.stage == "NEGOTIATING"

    transition_deal_stage(deal, "WON")
    deal.refresh_from_db()
    assert deal.stage == "WON"
    assert deal.won_at is not None

    record_learning_feedback(deal, "客户认可齿轮精度与交期。")
    deal.refresh_from_db()
    assert deal.feedback == "客户认可齿轮精度与交期。"


def test_deal_stage_vocabulary_is_complete():
    assert DEAL_STAGE_ORDER[0] == "QUOTE_CREATED"
    assert DEAL_STAGE_LABELS_ZH["WON"] == "已成交"
    assert DEAL_STAGE_LABELS_ZH["NURTURE"] == "长期培育"


def test_unknown_deal_stage_is_rejected(organization):
    account = TargetAccount.objects.create(organization=organization, name="Unknown", country="IDN")
    deal = SalesDeal.objects.create(organization=organization, account=account)
    with pytest.raises(ValueError):
        transition_deal_stage(deal, "NOT_A_STAGE")
