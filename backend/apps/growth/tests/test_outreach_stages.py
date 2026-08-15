import pytest

from apps.growth.models import FollowUp, TargetAccount
from apps.growth.outreach_stages import STAGE_LABELS_ZH, STAGE_ORDER, transition_stage
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Outreach stages", slug="outreach-stages")


def test_follow_up_has_default_stage_and_can_transition(organization):
    account = TargetAccount.objects.create(organization=organization, name="ABC Mining", country="IDN")
    follow_up = FollowUp.objects.create(organization=organization, account=account)

    assert follow_up.stage == FollowUp.Stage.QUALIFIED

    transition_stage(follow_up, "EMAIL_1_SENT")
    follow_up.refresh_from_db()
    assert follow_up.stage == "EMAIL_1_SENT"


def test_stage_vocabulary_is_complete_and_labeled():
    assert STAGE_ORDER[0] == "DISCOVERED"
    assert STAGE_ORDER[-2:] == ("WON", "LOST")
    assert STAGE_LABELS_ZH["WON"] == "已成交"


def test_unknown_stage_is_rejected(organization):
    account = TargetAccount.objects.create(organization=organization, name="Unknown", country="IDN")
    follow_up = FollowUp.objects.create(organization=organization, account=account)
    with pytest.raises(ValueError):
        transition_stage(follow_up, "NOT_A_STAGE")
