import pytest
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.identity.models import Organization
from apps.platforms.models import Platform
from apps.content.models import PlatformContent
from apps.publishing.models import PublishAttempt, PublishTask
from apps.publishing.services import publish_task_is_consistent
from apps.tracking.models import TrackingLink
from apps.tracking.services import TrackingConflict, create_short_link, create_tracking_link


def _create(context, **overrides):
    values = {
        "organization": context["organization"],
        "destination": "https://example.com/landing?ref=site",
        "utm_source": "LinkedIn",
        "utm_medium": "Social Post",
        "utm_campaign": "Gear Launch",
        "utm_content": "Hero",
        "campaign": context["campaign"],
        "platform": context["platform"],
        "product": context["product"],
        "published_post": context["published_post"],
        "idempotency_key": "tracking-request-1",
    }
    values.update(overrides)
    return create_tracking_link(**values)


@pytest.mark.django_db
def test_tracking_fixture_uses_canonical_publishing_success(tracking_context):
    post = tracking_context["published_post"]
    task = PublishTask.objects.select_related(
        "platform_content__master_content__brief", "social_account", "platform",
        "published_post__attempt",
    ).get(pk=post.task_id)
    assert publish_task_is_consistent(task)
    assert task.status == PublishTask.Status.SUCCEEDED
    assert post.attempt.status == PublishAttempt.Status.SUCCEEDED
    assert task.platform_content.status == PlatformContent.Status.PUBLISHED


@pytest.mark.django_db
def test_tracking_link_captures_canonical_immutable_snapshot(tracking_context):
    link = _create(tracking_context)
    assert link.utm_source == "linkedin"
    assert link.utm_medium == "social-post"
    assert link.utm_campaign == "gear-launch"
    assert link.full_url == (
        "https://example.com/landing?ref=site&utm_source=linkedin&utm_medium=social-post&"
        "utm_campaign=gear-launch&utm_content=hero"
    )

    link.destination = "https://example.com/changed"
    with pytest.raises(ValidationError):
        link.save()
    with pytest.raises(ValidationError):
        TrackingLink.objects.filter(pk=link.pk).update(utm_source="forged")
    with pytest.raises(ProtectedError):
        TrackingLink.objects.filter(pk=link.pk).delete()


@pytest.mark.django_db
def test_tracking_link_idempotency_is_org_scoped_and_fingerprinted(tracking_context):
    first = _create(tracking_context)
    assert _create(tracking_context).pk == first.pk
    with pytest.raises(TrackingConflict):
        _create(tracking_context, destination="https://example.com/other")


@pytest.mark.django_db
def test_tracking_link_rejects_cross_org_or_inconsistent_references(tracking_context):
    other = Organization.objects.create(name="Other", slug="other-tracking")
    with pytest.raises(TrackingConflict):
        _create(tracking_context, organization=other, idempotency_key="other")
    other_platform = Platform.objects.create(code="OTHER", name="Other")
    with pytest.raises(TrackingConflict):
        _create(tracking_context, platform=other_platform, idempotency_key="bad-platform")


@pytest.mark.django_db
def test_nfc_equivalent_destination_reuses_key_and_redirects_to_one_stable_url(
    client, tracking_context
):
    first = _create(
        tracking_context,
        destination="https://example.com/cafe\u0301?q=re\u0301sume\u0301#de\u0301tail",
        idempotency_key="nfc-equivalent",
    )
    second = _create(
        tracking_context,
        destination="https://example.com/caf%C3%A9?q=r%C3%A9sum%C3%A9#d%C3%A9tail",
        idempotency_key="nfc-equivalent",
    )
    assert second.pk == first.pk
    assert first.destination == (
        "https://example.com/caf%C3%A9?q=r%C3%A9sum%C3%A9#d%C3%A9tail"
    )
    short = create_short_link(
        organization=tracking_context["organization"], tracking_link=first,
        idempotency_key="nfc-equivalent-short",
    )
    response = client.get(f"/r/{short.code}", REMOTE_ADDR="198.51.100.20")
    assert response.status_code == 302
    assert response["Location"] == (
        "https://example.com/caf%C3%A9?q=r%C3%A9sum%C3%A9&"
        "utm_source=linkedin&utm_medium=social-post&utm_campaign=gear-launch&"
        "utm_content=hero#d%C3%A9tail"
    )
