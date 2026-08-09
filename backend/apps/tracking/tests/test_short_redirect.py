import pytest
from django.db import DatabaseError

from apps.content.models import PlatformContent, content_writes
from apps.publishing.models import PublishTask, publishing_writes
from apps.tracking.models import ClickEvent, ShortLink, TrackingLink, tracking_writes
from apps.tracking.services import (
    create_short_link, create_tracking_link, resolve_active_short_link, set_short_link_status,
)


def _links(context):
    tracking = create_tracking_link(
        organization=context["organization"], destination="https://example.com/path?x=1#part",
        utm_source="LinkedIn", utm_medium="Social", utm_campaign="Launch",
        campaign=context["campaign"], platform=context["platform"], product=context["product"],
        published_post=context["published_post"], idempotency_key="redirect-tracking",
    )
    short = create_short_link(
        organization=context["organization"], tracking_link=tracking,
        idempotency_key="redirect-short",
    )
    return tracking, short


@pytest.mark.django_db
def test_public_redirect_records_exactly_one_privacy_safe_event(client, tracking_context):
    tracking, short = _links(tracking_context)
    response = client.get(
        f"/r/{short.code}",
        REMOTE_ADDR="198.51.100.25",
        HTTP_USER_AGENT="Mozilla/5.0 (iPhone) Mobile secret-tail",
        HTTP_REFERER="https://REF.example/private/path?secret=yes",
        HTTP_COOKIE="tracking=forbidden",
    )
    assert response.status_code == 302
    assert response["Location"] == tracking.full_url
    event = ClickEvent.objects.get()
    assert event.device == ClickEvent.Device.MOBILE
    assert event.referrer_host == "ref.example"
    assert event.network_hash and "198.51.100.25" not in event.network_hash
    field_names = {field.name for field in ClickEvent._meta.fields}
    assert not {"ip", "user_agent", "referrer", "cookie", "headers", "fingerprint"} & field_names
    assert ClickEvent.objects.count() == 1


@pytest.mark.django_db
def test_disabled_or_corrupt_short_link_is_non_enumerating_404(client, tracking_context):
    tracking, short = _links(tracking_context)
    set_short_link_status(short, status=ShortLink.Status.DISABLED)
    assert client.get(f"/r/{short.code}", REMOTE_ADDR="198.51.100.25").status_code == 404
    set_short_link_status(short, status=ShortLink.Status.ACTIVE)
    with tracking_writes():
        TrackingLink.objects.filter(pk=tracking.pk).update(full_url="https://evil.example/")
    assert client.get(f"/r/{short.code}", REMOTE_ADDR="198.51.100.25").status_code == 404
    assert ClickEvent.objects.count() == 0


@pytest.mark.django_db
def test_percent_encoded_control_corruption_never_redirects_or_records(client, tracking_context):
    tracking, short = _links(tracking_context)
    with tracking_writes():
        TrackingLink.objects.filter(pk=tracking.pk).update(
            destination="https://example.com/%0D%0Aheader"
        )
    response = client.get(f"/r/{short.code}", REMOTE_ADDR="198.51.100.25")
    assert response.status_code == 404
    assert "Location" not in response
    assert ClickEvent.objects.count() == 0


@pytest.mark.django_db
def test_database_failure_returns_generic_503_without_redirect(client, tracking_context, monkeypatch):
    _tracking, short = _links(tracking_context)
    monkeypatch.setattr(
        "apps.tracking.views.record_click_event",
        lambda **_kwargs: (_ for _ in ()).throw(DatabaseError("sensitive database details")),
    )
    response = client.get(f"/r/{short.code}", REMOTE_ADDR="198.51.100.25")
    assert response.status_code == 503
    assert "Location" not in response
    assert b"sensitive" not in response.content
    assert ClickEvent.objects.count() == 0


@pytest.mark.django_db
def test_malformed_trusted_forwarding_records_nothing_and_does_not_redirect(
    client, tracking_context, settings
):
    _tracking, short = _links(tracking_context)
    settings.TRACKING_TRUSTED_PROXY_CIDRS = ["10.0.0.0/8"]
    response = client.get(
        f"/r/{short.code}", REMOTE_ADDR="10.1.2.3",
        HTTP_X_FORWARDED_FOR="203.0.113.2, 203.0.113.3",
    )
    assert response.status_code == 400
    assert "Location" not in response
    assert ClickEvent.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_fingerprint", "f" * 64),
        ("idempotency_key", " invalid "),
        ("utm_source", "LinkedIn"),
    ],
)
def test_redirect_rejects_tracking_identity_or_fingerprint_corruption(
    tracking_context, field, value
):
    tracking, short = _links(tracking_context)
    with tracking_writes():
        TrackingLink.objects.filter(pk=tracking.pk).update(**{field: value})
    assert resolve_active_short_link(short.code) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_fingerprint", "f" * 64),
        ("idempotency_key", " invalid "),
        ("code", "arbitrary-code"),
        ("status", "BROKEN"),
    ],
)
def test_redirect_rejects_short_identity_status_or_code_corruption(
    tracking_context, field, value
):
    _tracking, short = _links(tracking_context)
    with tracking_writes():
        ShortLink.objects.filter(pk=short.pk).update(**{field: value})
    assert resolve_active_short_link(value if field == "code" else short.code) is None


@pytest.mark.django_db
def test_redirect_reuses_canonical_publish_task_consistency(tracking_context):
    _tracking, short = _links(tracking_context)
    with publishing_writes():
        PublishTask.objects.filter(pk=tracking_context["published_post"].task_id).update(
            request_fingerprint="f" * 64
        )
    assert resolve_active_short_link(short.code) is None


@pytest.mark.django_db
def test_redirect_requires_exact_published_content_status(tracking_context):
    _tracking, short = _links(tracking_context)
    with content_writes():
        PlatformContent.objects.filter(pk=tracking_context["content"].pk).update(
            status=PlatformContent.Status.APPROVED
        )
    assert resolve_active_short_link(short.code) is None
