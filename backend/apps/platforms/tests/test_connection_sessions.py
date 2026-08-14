import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.connection_sessions import (
    ConnectionCandidate,
    ConnectionSessionInvalid,
    confirm_connection_session,
    create_connection_session,
    get_connection_session,
)
from apps.platforms.models import (
    AccountConnectionSession,
    ConnectorCredential,
    Platform,
    SocialAccount,
)


def candidate(
    *, channel: str = "FACEBOOK", external_id: str = "page-123",
    display_name: str = "Acme Page", candidate_id: str | None = None,
) -> ConnectionCandidate:
    return ConnectionCandidate(
        candidate_id=candidate_id or str(uuid4()),
        external_id=external_id,
        display_name=display_name,
        channel=channel,
        capabilities=("PUBLISH", "METRICS_READ"),
        discovered_at=timezone.now(),
    )


@pytest.fixture
def session_context(db):
    user_model = get_user_model()
    actor = user_model.objects.create_user(username="connection-admin")
    other_actor = user_model.objects.create_user(username="connection-other")
    organization = Organization.objects.create(name="Acme", slug="connection-session-acme")
    other_organization = Organization.objects.create(name="Other", slug="connection-session-other")
    platform = Platform.objects.create(code="FACEBOOK", name="Facebook")
    return actor, other_actor, organization, other_organization, platform


def test_connection_session_is_short_lived_and_persists_only_safe_candidates(session_context) -> None:
    actor, _other_actor, organization, _other_org, platform = session_context
    selected = candidate()

    session = create_connection_session(
        organization=organization,
        actor=actor,
        platform=platform,
        secret_reference="vault://fixture/account-1",
        credential_expires_at=timezone.now() + timedelta(hours=1),
        candidates=[selected],
        granted_capabilities=["PUBLISH", "METRICS_READ"],
    )

    lifetime = session.expires_at - session.created_at
    assert timedelta(minutes=10) - timedelta(seconds=1) <= lifetime <= timedelta(minutes=10, seconds=1)
    assert session.candidates == [{
        "candidate_id": selected.candidate_id,
        "external_id": "page-123",
        "display_name": "Acme Page",
        "channel": "FACEBOOK",
        "capabilities": ["PUBLISH", "METRICS_READ"],
        "discovered_at": selected.discovered_at.isoformat(),
    }]
    assert "token" not in json.dumps(session.candidates).lower()
    assert session.secret_reference == "vault://fixture/account-1"
    assert session.confirmed_candidate_id == ""


def test_connection_session_rejects_unbounded_duplicate_or_unsupported_candidates(session_context) -> None:
    actor, _other_actor, organization, _other_org, platform = session_context
    duplicate_id = str(uuid4())
    invalid_sets = [
        [candidate(external_id=f"page-{index}") for index in range(101)],
        [candidate(candidate_id=duplicate_id), candidate(candidate_id=duplicate_id, external_id="page-456")],
        [candidate(external_id="page-duplicate"), candidate(external_id="page-duplicate")],
        [candidate(channel="YOUTUBE")],
    ]

    for candidates in invalid_sets:
        with pytest.raises(ValueError):
            create_connection_session(
                organization=organization,
                actor=actor,
                platform=platform,
                secret_reference="vault://fixture/rejected",
                credential_expires_at=None,
                candidates=candidates,
                granted_capabilities=["PUBLISH"],
            )

    assert AccountConnectionSession.objects.count() == 0


def test_connection_session_read_is_actor_and_organization_bound_and_expires(session_context) -> None:
    actor, other_actor, organization, other_organization, platform = session_context
    session = create_connection_session(
        organization=organization,
        actor=actor,
        platform=platform,
        secret_reference="vault://fixture/account-2",
        credential_expires_at=None,
        candidates=[candidate()],
        granted_capabilities=["PUBLISH"],
    )

    assert get_connection_session(
        session_id=session.id, organization=organization, actor=actor,
    ).id == session.id
    with pytest.raises(ConnectionSessionInvalid):
        get_connection_session(
            session_id=session.id, organization=organization, actor=other_actor,
        )
    with pytest.raises(ConnectionSessionInvalid):
        get_connection_session(
            session_id=session.id, organization=other_organization, actor=actor,
        )

    AccountConnectionSession.objects.filter(pk=session.id).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    with pytest.raises(ConnectionSessionInvalid, match="CONNECTION_SESSION_EXPIRED"):
        get_connection_session(
            session_id=session.id, organization=organization, actor=actor,
        )


def test_confirmation_atomically_connects_exact_candidate_and_is_same_candidate_idempotent(session_context) -> None:
    actor, _other_actor, organization, _other_org, platform = session_context
    selected = candidate()
    unselected = candidate(external_id="page-456", display_name="Other Page")
    session = create_connection_session(
        organization=organization,
        actor=actor,
        platform=platform,
        secret_reference="vault://fixture/account-3",
        credential_expires_at=timezone.now() + timedelta(hours=1),
        candidates=[selected, unselected],
        granted_capabilities=["PUBLISH", "METRICS_READ"],
    )

    with pytest.raises(ConnectionSessionInvalid, match="CANDIDATE_NOT_FOUND"):
        confirm_connection_session(session=session, candidate_id=str(uuid4()))
    account = confirm_connection_session(session=session, candidate_id=selected.candidate_id)
    replay = confirm_connection_session(session=session, candidate_id=selected.candidate_id)

    session.refresh_from_db()
    assert replay.id == account.id
    assert session.consumed_at is not None
    assert session.confirmed_candidate_id == selected.candidate_id
    assert ConnectorCredential.objects.filter(
        organization=organization,
        platform=platform,
        secret_reference="vault://fixture/account-3",
        granted_scopes=["PUBLISH", "METRICS_READ"],
    ).count() == 1
    assert SocialAccount.objects.filter(
        organization=organization,
        platform=platform,
        external_id="page-123",
        display_name="Acme Page",
        publish_mode=SocialAccount.PublishMode.API_CONFIRM,
        connector_metadata__connection_kind="official_oauth",
    ).count() == 1

    with pytest.raises(ConnectionSessionInvalid, match="CONNECTION_SESSION_CONSUMED"):
        get_connection_session(
            session_id=session.id, organization=organization, actor=actor,
        )

    with pytest.raises(ConnectionSessionInvalid, match="CONNECTION_SESSION_CONSUMED"):
        confirm_connection_session(session=session, candidate_id=unselected.candidate_id)
