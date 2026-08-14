import hashlib
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.models import OAuthConnectionAttempt, Platform
from apps.platforms.oauth import (
    AuthorizationAttemptInvalid,
    create_authorization_attempt,
    consume_authorization_attempt,
)


@pytest.fixture
def oauth_context():
    organization = Organization.objects.create(name="Acme", slug="oauth-acme")
    actor = get_user_model().objects.create_user(username="oauth-admin")
    other_actor = get_user_model().objects.create_user(username="oauth-other")
    platform = Platform.objects.create(code="META", name="Meta")
    return organization, actor, other_actor, platform


@pytest.mark.django_db
def test_authorization_state_is_hashed_short_lived_and_consumed_once(oauth_context) -> None:
    organization, actor, _other_actor, platform = oauth_context

    started = create_authorization_attempt(
        organization=organization,
        actor=actor,
        platform=platform,
        return_path="/promotion",
    )

    attempt = OAuthConnectionAttempt.objects.get(pk=started.attempt_id)
    assert len(started.raw_state) >= 32
    assert attempt.state_hash == hashlib.sha256(started.raw_state.encode()).hexdigest()
    assert started.raw_state not in attempt.state_hash
    assert timedelta(minutes=9, seconds=50) <= attempt.expires_at - attempt.created_at <= timedelta(minutes=10)

    consumed = consume_authorization_attempt(
        raw_state=started.raw_state,
        actor=actor,
        platform_code="META",
    )
    assert consumed.pk == attempt.pk
    assert consumed.consumed_at is not None

    with pytest.raises(AuthorizationAttemptInvalid):
        consume_authorization_attempt(
            raw_state=started.raw_state,
            actor=actor,
            platform_code="META",
        )


@pytest.mark.django_db
def test_authorization_state_rejects_wrong_actor_provider_and_expiry(oauth_context) -> None:
    organization, actor, other_actor, platform = oauth_context
    linkedin = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    wrong_actor = create_authorization_attempt(
        organization=organization, actor=actor, platform=platform, return_path="/promotion",
    )
    wrong_provider = create_authorization_attempt(
        organization=organization, actor=actor, platform=platform, return_path="/promotion",
    )
    expired = create_authorization_attempt(
        organization=organization, actor=actor, platform=linkedin, return_path="/promotion",
    )
    OAuthConnectionAttempt.objects.filter(pk=expired.attempt_id).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    with pytest.raises(AuthorizationAttemptInvalid):
        consume_authorization_attempt(
            raw_state=wrong_actor.raw_state, actor=other_actor, platform_code="META",
        )
    with pytest.raises(AuthorizationAttemptInvalid):
        consume_authorization_attempt(
            raw_state=wrong_provider.raw_state, actor=actor, platform_code="LINKEDIN",
        )
    with pytest.raises(AuthorizationAttemptInvalid):
        consume_authorization_attempt(
            raw_state=expired.raw_state, actor=actor, platform_code="LINKEDIN",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "return_path",
    ["promotion", "//evil.example/steal", "https://evil.example/steal", "/\\evil.example"],
)
def test_authorization_attempt_rejects_non_local_return_paths(oauth_context, return_path: str) -> None:
    organization, actor, _other_actor, platform = oauth_context

    with pytest.raises(ValueError, match="return path"):
        create_authorization_attempt(
            organization=organization,
            actor=actor,
            platform=platform,
            return_path=return_path,
        )
