import pytest
from django.core.exceptions import ValidationError

from apps.tracking.models import ShortLink
from apps.tracking.services import (
    TrackingConflict,
    create_short_link,
    create_tracking_link,
    set_short_link_status,
)


def _tracking(context, key="tracking-short"):
    return create_tracking_link(
        organization=context["organization"],
        destination="https://example.com/landing",
        utm_source="LinkedIn",
        utm_medium="Social",
        utm_campaign="Launch",
        campaign=context["campaign"],
        platform=context["platform"],
        product=context["product"],
        published_post=context["published_post"],
        idempotency_key=key,
    )


@pytest.mark.django_db
def test_short_link_creation_is_idempotent_and_identity_is_immutable(tracking_context):
    tracking = _tracking(tracking_context)
    first = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="short-1",
    )
    assert len(first.code) >= 10
    assert not first.code.isdecimal()
    assert create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="short-1",
    ).pk == first.pk

    first.code = "forged-code"
    with pytest.raises(ValidationError):
        first.save()

    disabled = set_short_link_status(first, status=ShortLink.Status.DISABLED)
    assert disabled.status == ShortLink.Status.DISABLED


@pytest.mark.django_db
def test_short_link_key_conflict_and_cross_org_are_controlled(tracking_context):
    first_tracking = _tracking(tracking_context)
    second_tracking = _tracking(tracking_context, key="tracking-short-2")
    create_short_link(
        organization=tracking_context["organization"], tracking_link=first_tracking,
        idempotency_key="shared-short-key",
    )
    with pytest.raises(TrackingConflict):
        create_short_link(
            organization=tracking_context["organization"], tracking_link=second_tracking,
            idempotency_key="shared-short-key",
        )


@pytest.mark.django_db
def test_short_code_collision_retries_without_sequential_fallback(tracking_context, monkeypatch):
    tracking = _tracking(tracking_context)
    existing = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="existing-code",
    )
    codes = iter([existing.code, "s_ABCDEFGHIJKL"])
    monkeypatch.setattr("apps.tracking.services.generate_short_code", lambda: next(codes))
    created = create_short_link(
        organization=tracking_context["organization"], tracking_link=tracking,
        idempotency_key="collision-retry",
    )
    assert created.code == "s_ABCDEFGHIJKL"
