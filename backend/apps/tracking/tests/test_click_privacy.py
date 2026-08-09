from datetime import date, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tracking.models import ClickEvent
from apps.identity.models import Membership, Role
from apps.tracking.privacy import (
    PrivacyError,
    classify_device,
    daily_network_hash,
    extract_network_context,
    normalize_referrer_host,
    validate_tracking_configuration,
)
from apps.tracking.services import (
    create_short_link, create_tracking_link, purge_click_events, record_click_event,
)


def test_trusted_proxy_uses_one_forwarded_ip_and_country(settings):
    settings.TRACKING_TRUSTED_PROXY_CIDRS = ["10.0.0.0/8"]
    context = extract_network_context(
        {
            "REMOTE_ADDR": "10.1.2.3",
            "HTTP_X_FORWARDED_FOR": "203.0.113.42",
            "HTTP_X_COUNTRY_CODE": "de",
        }
    )
    assert context == ("203.0.113.42", "DE")


def test_untrusted_peer_ignores_spoofed_forwarding_and_country(settings):
    settings.TRACKING_TRUSTED_PROXY_CIDRS = ["10.0.0.0/8"]
    assert extract_network_context(
        {
            "REMOTE_ADDR": "198.51.100.19",
            "HTTP_X_FORWARDED_FOR": "203.0.113.42",
            "HTTP_X_COUNTRY_CODE": "DE",
        }
    ) == ("198.51.100.19", "")


@pytest.mark.parametrize("forwarded", ["bad-ip", "203.0.113.1, 203.0.113.2", ""])
def test_trusted_proxy_malformed_or_multiple_forwarding_fails_closed(settings, forwarded):
    settings.TRACKING_TRUSTED_PROXY_CIDRS = ["10.0.0.0/8"]
    with pytest.raises(PrivacyError):
        extract_network_context(
            {"REMOTE_ADDR": "10.1.2.3", "HTTP_X_FORWARDED_FOR": forwarded}
        )


def test_daily_hash_uses_coarse_prefix_and_rotates_by_date(settings):
    settings.TRACKING_HASH_SECRET = "test-secret-that-is-definitely-at-least-32-bytes"
    settings.TRACKING_HASH_VERSION = "v1"
    today = date(2026, 8, 9)
    assert daily_network_hash("203.0.113.4", today) == daily_network_hash("203.0.113.222", today)
    assert daily_network_hash("2001:db8:abcd:1201::1", today) == daily_network_hash(
        "2001:db8:abcd:12ff::9", today
    )
    assert daily_network_hash("203.0.113.4", today) != daily_network_hash(
        "203.0.113.4", today + timedelta(days=1)
    )


def test_configuration_rejects_missing_or_insecure_secret(settings):
    settings.TRACKING_HASH_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        validate_tracking_configuration()
    settings.TRACKING_HASH_SECRET = "development-only-tracking-secret"
    with pytest.raises(ImproperlyConfigured):
        validate_tracking_configuration()


def test_device_and_referrer_are_coarse_only():
    assert classify_device("Mozilla/5.0 (iPhone) Mobile") == ClickEvent.Device.MOBILE
    assert classify_device("Googlebot/2.1") == ClickEvent.Device.BOT
    assert classify_device("Mozilla/5.0 (iPad) Tablet") == ClickEvent.Device.TABLET
    assert classify_device("Mozilla/5.0 (Windows NT 10.0)") == ClickEvent.Device.DESKTOP
    assert normalize_referrer_host("https://User:pass@EXAMPLE.com/private?q=secret") == "example.com"
    assert normalize_referrer_host("not a url") == ""


@pytest.mark.django_db
def test_click_event_normal_paths_are_append_only():
    with pytest.raises(ValidationError):
        ClickEvent.objects.create()


@pytest.mark.django_db
def test_retention_purge_is_permissioned_scoped_and_explicit(tracking_context):
    tracking = create_tracking_link(
        organization=tracking_context["organization"], destination="https://example.com/",
        utm_source="linkedin", utm_medium="social", utm_campaign="launch",
        campaign=tracking_context["campaign"], platform=tracking_context["platform"],
        product=tracking_context["product"], published_post=tracking_context["published_post"],
        idempotency_key="purge-tracking",
    )
    short = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="purge-short",
    )
    old = timezone.now() - timedelta(days=40)
    record_click_event(short_link=short, occurred_at=old, meta={"REMOTE_ADDR": "198.51.100.2"})
    record_click_event(short_link=short, occurred_at=timezone.now(), meta={"REMOTE_ADDR": "198.51.100.2"})
    reviewer = get_user_model().objects.create_user(username="purge-reviewer")
    reviewer_membership = Membership.objects.create(
        user=reviewer, organization=tracking_context["organization"], role=Role.objects.create_reviewer()
    )
    with pytest.raises(PermissionDenied):
        purge_click_events(membership=reviewer_membership, before=timezone.now() - timedelta(days=30))
    operator = get_user_model().objects.create_user(username="purge-operator")
    operator_membership = Membership.objects.create(
        user=operator, organization=tracking_context["organization"], role=Role.objects.create_operator()
    )
    assert purge_click_events(
        membership=operator_membership, before=timezone.now() - timedelta(days=30)
    ) == 1
    assert ClickEvent.objects.count() == 1
