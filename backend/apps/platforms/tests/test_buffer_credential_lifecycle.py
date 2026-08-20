from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.platforms.models import (
    ProviderConnection,
    ProviderConnectionEvent,
    provider_event_writes,
)
from apps.platforms.provider_connections import (
    BufferConnectionError,
    disconnect_buffer,
    probe_buffer_connection,
)

from .buffer_test_utils import connected_connection, probe_ok


class FailingDeleteTokenStore:
    def __init__(self):
        self.deleted = []

    def store(self, bundle, context):
        return "vault://buffer/new"

    def resolve(self, reference):
        raise AssertionError("unexpected resolve")

    def delete(self, reference):
        raise RuntimeError("credential delete failed")


@pytest.mark.django_db
def test_disconnect_preserves_reference_when_delete_fails(organization):
    connection = connected_connection(organization)

    with pytest.raises(RuntimeError):
        disconnect_buffer(
            organization=organization,
            actor=None,
            token_store=FailingDeleteTokenStore(),
        )

    connection.refresh_from_db()
    assert connection.credential_reference == "vault://buffer/existing"
    assert connection.connection_state == ProviderConnection.ConnectionState.CONNECTED


@pytest.mark.django_db
def test_probe_detects_concurrent_rotation(organization):
    connection = connected_connection(organization)

    class RotatingConnector:
        def probe_connection(self, request):
            ProviderConnection.objects.filter(pk=connection.pk).update(
                credential_reference="vault://buffer/rotated",
            )
            return probe_ok()

    with pytest.raises(BufferConnectionError) as exc_info:
        probe_buffer_connection(
            organization=organization,
            actor=None,
            connector=RotatingConnector(),
        )

    assert exc_info.value.code == "BUFFER_CONNECTION_CHANGED"
    connection.refresh_from_db()
    assert connection.credential_reference == "vault://buffer/rotated"
    assert connection.connection_state == ProviderConnection.ConnectionState.CONNECTED


@pytest.mark.django_db
def test_bulk_create_rejects_sensitive_metadata(organization):
    connection = connected_connection(organization)
    event = ProviderConnectionEvent(
        organization=organization,
        provider_connection=connection,
        provider="BUFFER",
        actor=None,
        action=ProviderConnectionEvent.Action.SYNC,
        outcome=ProviderConnectionEvent.Outcome.SUCCESS,
        metadata={"access_token": "secret"},
    )

    with pytest.raises(ValidationError):
        with provider_event_writes():
            ProviderConnectionEvent.objects.bulk_create([event])
