from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from apps.common.tenant_tasks import tenant_task_context as real_tenant_task_context
from apps.identity.models import Organization
from apps.platforms.models import (
    EncryptedOAuthCredential,
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
def test_probe_detects_concurrent_state_change(organization):
    connection = connected_connection(organization)

    class StateChangingConnector:
        def probe_connection(self, request):
            ProviderConnection.objects.filter(pk=connection.pk).update(
                connection_state=ProviderConnection.ConnectionState.REAUTHORIZATION_REQUIRED,
            )
            return probe_ok()

    with pytest.raises(BufferConnectionError) as exc_info:
        probe_buffer_connection(
            organization=organization,
            actor=None,
            connector=StateChangingConnector(),
        )

    assert exc_info.value.code == "BUFFER_CONNECTION_CHANGED"
    connection.refresh_from_db()
    assert connection.connection_state == ProviderConnection.ConnectionState.REAUTHORIZATION_REQUIRED


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


@pytest.mark.django_db
def test_orphan_reclamation_command_reclaims_only_unreferenced_credentials(
    organization, monkeypatch, capsys
):
    connection = connected_connection(organization, reference="vault://buffer/kept")
    kept = EncryptedOAuthCredential.objects.create(
        organization=organization,
        reference="vault://buffer/kept",
        actor_identifier="actor",
        platform_code="BUFFER",
        connection_attempt_id=uuid4(),
        key_version="v1",
        status=EncryptedOAuthCredential.Status.ACTIVE,
    )
    old_orphan = EncryptedOAuthCredential.objects.create(
        organization=organization,
        reference="vault://buffer/orphan-old",
        actor_identifier="actor",
        platform_code="BUFFER",
        connection_attempt_id=uuid4(),
        key_version="v1",
        status=EncryptedOAuthCredential.Status.ACTIVE,
    )
    EncryptedOAuthCredential.objects.filter(pk=old_orphan.pk).update(
        updated_at=timezone.now() - timedelta(hours=2),
    )
    fresh_orphan = EncryptedOAuthCredential.objects.create(
        organization=organization,
        reference="vault://buffer/orphan-fresh",
        actor_identifier="actor",
        platform_code="BUFFER",
        connection_attempt_id=uuid4(),
        key_version="v1",
        status=EncryptedOAuthCredential.Status.ACTIVE,
    )
    other = Organization.objects.create(name="Other", slug=f"other-{uuid4()}")
    other_orphan = EncryptedOAuthCredential.objects.create(
        organization=other,
        reference="vault://buffer/other-orphan",
        actor_identifier="actor",
        platform_code="BUFFER",
        connection_attempt_id=uuid4(),
        key_version="v1",
        status=EncryptedOAuthCredential.Status.ACTIVE,
    )
    EncryptedOAuthCredential.objects.filter(pk=other_orphan.pk).update(
        updated_at=timezone.now() - timedelta(hours=2),
    )
    seen = []

    @contextmanager
    def recording_tenant_context(organization_id):
        seen.append(organization_id)
        with real_tenant_task_context(organization_id) as parsed:
            yield parsed

    monkeypatch.setattr(
        "apps.platforms.management.commands.reclaim_orphan_buffer_credentials."
        "tenant_task_context",
        recording_tenant_context,
    )
    assert connection.credential_reference == kept.reference

    call_command("reclaim_orphan_buffer_credentials", verbosity=0)

    kept.refresh_from_db()
    old_orphan.refresh_from_db()
    fresh_orphan.refresh_from_db()
    other_orphan.refresh_from_db()
    assert kept.status == EncryptedOAuthCredential.Status.ACTIVE
    assert old_orphan.status == EncryptedOAuthCredential.Status.DISCONNECTED
    assert fresh_orphan.status == EncryptedOAuthCredential.Status.ACTIVE
    assert other_orphan.status == EncryptedOAuthCredential.Status.DISCONNECTED
    assert seen == sorted((str(organization.id), str(other.id)))
    output = capsys.readouterr().out
    assert "vault://" not in output
