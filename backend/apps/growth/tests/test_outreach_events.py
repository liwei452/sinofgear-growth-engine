import pytest

from apps.growth.models import FollowUp, OutreachDraft, OutreachMessage, TargetAccount
from apps.growth.outreach_events import (
    record_bounce,
    record_reply,
    record_sent,
    record_unsubscribe,
)
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Outreach", slug="outreach")


def _account_and_draft(organization):
    account = TargetAccount.objects.create(
        organization=organization,
        name="Acme",
        country="VN",
    )
    draft = OutreachDraft.objects.create(
        organization=organization,
        account=account,
        english_draft="Hello team",
        chinese_explanation="test",
    )
    FollowUp.objects.create(organization=organization, account=account)
    return account, draft


def test_send_reply_bounce_unsubscribe_state_machine(organization):
    account, draft = _account_and_draft(organization)
    message = record_sent(account=account, draft=draft, email="a@example.com")
    assert message.status == OutreachMessage.Status.SENT
    assert FollowUp.objects.get(account=account).stage == "EMAIL_1_SENT"

    record_reply(account=account)
    message.refresh_from_db()
    assert message.status == OutreachMessage.Status.REPLIED
    assert FollowUp.objects.get(account=account).stage == "REPLIED"

    account2, draft2 = _account_and_draft(organization)
    record_sent(account=account2, draft=draft2, email="b@example.com")
    record_bounce(account=account2)
    assert FollowUp.objects.get(account=account2).stage == "BOUNCED"

    account3, draft3 = _account_and_draft(organization)
    record_sent(account=account3, draft=draft3, email="c@example.com")
    record_unsubscribe(account=account3)
    assert FollowUp.objects.get(account=account3).stage == "UNSUBSCRIBED"


def test_smtp_provider_sends_through_django_mail(settings):
    from django.core import mail

    from apps.growth.email_delivery import SMTPEmailDeliveryProvider

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    provider = SMTPEmailDeliveryProvider()
    result = provider.send(email="a@example.com", subject="Hi", body="Body")

    assert result["status"] == "SENT"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["a@example.com"]
