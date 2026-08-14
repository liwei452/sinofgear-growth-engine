import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import transaction
from django.utils import timezone

from .models import OAuthConnectionAttempt


class AuthorizationAttemptInvalid(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorizationStart:
    attempt_id: object
    raw_state: str
    expires_at: object


def _state_hash(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _validate_return_path(return_path: str) -> str:
    if not isinstance(return_path, str):
        raise ValueError("A safe local return path is required.")
    parsed = urlsplit(return_path)
    if (
        not return_path.startswith("/")
        or return_path.startswith("//")
        or "\\" in return_path
        or parsed.scheme
        or parsed.netloc
    ):
        raise ValueError("A safe local return path is required.")
    return return_path


def create_authorization_attempt(
    *, organization, actor, platform, return_path: str,
) -> AuthorizationStart:
    safe_return_path = _validate_return_path(return_path)
    raw_state = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(minutes=10)
    attempt = OAuthConnectionAttempt.objects.create(
        organization=organization,
        actor=actor,
        platform=platform,
        state_hash=_state_hash(raw_state),
        return_path=safe_return_path,
        expires_at=expires_at,
    )
    return AuthorizationStart(
        attempt_id=attempt.id,
        raw_state=raw_state,
        expires_at=expires_at,
    )


def consume_authorization_attempt(
    *, raw_state: str, actor, platform_code: str,
) -> OAuthConnectionAttempt:
    if not isinstance(raw_state, str) or not raw_state:
        raise AuthorizationAttemptInvalid("Authorization attempt is invalid or expired.")
    expected_hash = _state_hash(raw_state)
    with transaction.atomic():
        attempt = OAuthConnectionAttempt.objects.select_for_update().filter(
            state_hash=expected_hash,
            actor=actor,
            platform__code=platform_code,
        ).first()
        if (
            attempt is None
            or not secrets.compare_digest(attempt.state_hash, expected_hash)
            or attempt.consumed_at is not None
            or attempt.expires_at <= timezone.now()
        ):
            raise AuthorizationAttemptInvalid("Authorization attempt is invalid or expired.")
        attempt.consumed_at = timezone.now()
        attempt.save(update_fields=["consumed_at", "updated_at"])
        return attempt
