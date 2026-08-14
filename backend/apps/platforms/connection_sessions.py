from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .codes import validate_capability_list
from .models import (
    AccountConnectionSession,
    ConnectorCredential,
    Platform,
    SocialAccount,
)


SUPPORTED_CHANNELS = frozenset({"FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK"})
MAX_CANDIDATES = 100


class ConnectionSessionInvalid(RuntimeError):
    pass


@dataclass(frozen=True)
class ConnectionCandidate:
    candidate_id: str
    external_id: str
    display_name: str
    channel: str
    capabilities: tuple[str, ...]
    discovered_at: datetime


def _validated_capabilities(capabilities) -> list[str]:
    normalized = list(capabilities)
    try:
        validate_capability_list(normalized)
    except ValidationError as error:
        raise ValueError("Invalid account capabilities.") from error
    if len(normalized) != len(set(normalized)):
        raise ValueError("Account capabilities must be unique.")
    return normalized


def _candidate_payload(candidate: ConnectionCandidate) -> dict:
    try:
        UUID(candidate.candidate_id)
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("Candidate ID must be a UUID.") from error
    if not isinstance(candidate.external_id, str) or not 1 <= len(candidate.external_id) <= 255:
        raise ValueError("Candidate external ID is invalid.")
    if not isinstance(candidate.display_name, str) or not 1 <= len(candidate.display_name) <= 255:
        raise ValueError("Candidate display name is invalid.")
    if candidate.channel not in SUPPORTED_CHANNELS:
        raise ValueError("Candidate channel is unsupported.")
    if not isinstance(candidate.discovered_at, datetime) or timezone.is_naive(candidate.discovered_at):
        raise ValueError("Candidate discovery time must be timezone-aware.")
    return {
        "candidate_id": candidate.candidate_id,
        "external_id": candidate.external_id,
        "display_name": candidate.display_name,
        "channel": candidate.channel,
        "capabilities": _validated_capabilities(candidate.capabilities),
        "discovered_at": candidate.discovered_at.isoformat(),
    }


def create_connection_session(
    *, organization, actor, platform, secret_reference: str,
    credential_expires_at, candidates: list[ConnectionCandidate],
    granted_capabilities,
) -> AccountConnectionSession:
    if not isinstance(secret_reference, str) or not 1 <= len(secret_reference) <= 512:
        raise ValueError("A safe credential reference is required.")
    if not candidates or len(candidates) > MAX_CANDIDATES:
        raise ValueError("Between one and 100 account candidates are required.")
    payloads = [_candidate_payload(candidate) for candidate in candidates]
    candidate_ids = [item["candidate_id"] for item in payloads]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("Candidate IDs must be unique.")
    account_keys = [(item["channel"], item["external_id"]) for item in payloads]
    if len(account_keys) != len(set(account_keys)):
        raise ValueError("Provider accounts must be unique per channel.")
    if credential_expires_at is not None and (
        not isinstance(credential_expires_at, datetime)
        or timezone.is_naive(credential_expires_at)
    ):
        raise ValueError("Credential expiry must be timezone-aware.")
    return AccountConnectionSession.objects.create(
        organization=organization,
        actor=actor,
        platform=platform,
        secret_reference=secret_reference,
        candidates=payloads,
        granted_capabilities=_validated_capabilities(granted_capabilities),
        credential_expires_at=credential_expires_at,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def get_connection_session(
    *, session_id, organization, actor,
) -> AccountConnectionSession:
    session = AccountConnectionSession.objects.filter(
        pk=session_id,
        organization=organization,
        actor=actor,
    ).first()
    if session is None:
        raise ConnectionSessionInvalid("CONNECTION_SESSION_INVALID")
    if session.expires_at <= timezone.now():
        raise ConnectionSessionInvalid("CONNECTION_SESSION_EXPIRED")
    if session.consumed_at is not None:
        raise ConnectionSessionInvalid("CONNECTION_SESSION_CONSUMED")
    return session


def _candidate_for(session: AccountConnectionSession, candidate_id: str) -> dict | None:
    if not isinstance(session.candidates, list):
        return None
    return next((
        item for item in session.candidates
        if isinstance(item, dict) and item.get("candidate_id") == candidate_id
    ), None)


def confirm_connection_session(
    *, session: AccountConnectionSession, candidate_id: str,
) -> SocialAccount:
    with transaction.atomic():
        locked = AccountConnectionSession.objects.select_for_update().get(pk=session.pk)
        if locked.expires_at <= timezone.now():
            raise ConnectionSessionInvalid("CONNECTION_SESSION_EXPIRED")
        candidate = _candidate_for(locked, candidate_id)
        if locked.consumed_at is not None:
            if locked.confirmed_candidate_id != candidate_id or candidate is None:
                raise ConnectionSessionInvalid("CONNECTION_SESSION_CONSUMED")
            try:
                return SocialAccount.objects.get(
                    organization=locked.organization,
                    platform__code=candidate["channel"],
                    external_id=candidate["external_id"],
                )
            except SocialAccount.DoesNotExist as error:
                raise ConnectionSessionInvalid("CONNECTION_SESSION_INVALID") from error
        if candidate is None:
            raise ConnectionSessionInvalid("CANDIDATE_NOT_FOUND")
        try:
            platform = Platform.objects.get(code=candidate["channel"])
        except Platform.DoesNotExist as error:
            raise ConnectionSessionInvalid("CANDIDATE_NOT_FOUND") from error
        credential, _created = ConnectorCredential.objects.update_or_create(
            organization=locked.organization,
            platform=platform,
            secret_reference=locked.secret_reference,
            defaults={
                "granted_scopes": locked.granted_capabilities,
                "expires_at": locked.credential_expires_at,
            },
        )
        account, _created = SocialAccount.objects.update_or_create(
            organization=locked.organization,
            platform=platform,
            external_id=candidate["external_id"],
            defaults={
                "credential": credential,
                "display_name": candidate["display_name"],
                "publish_mode": SocialAccount.PublishMode.API_CONFIRM,
                "status": SocialAccount.Status.ACTIVE,
                "connector_metadata": {"connection_kind": "official_oauth"},
            },
        )
        locked.confirmed_candidate_id = candidate_id
        locked.consumed_at = timezone.now()
        locked.save(update_fields=["confirmed_candidate_id", "consumed_at", "updated_at"])
        return account
