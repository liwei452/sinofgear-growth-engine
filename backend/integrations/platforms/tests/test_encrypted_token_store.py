import base64
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.models import EncryptedOAuthCredential
from integrations.platforms.authorization import ProviderCredentialBundle
from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.encrypted_token_store import EncryptedDatabaseTokenStore
from integrations.platforms.secret_resolver import FixtureSecretResolver
from integrations.platforms.token_store import OAuthTokenSet, TokenStoreContext


def key(value: bytes = b"K" * 32) -> str:
    return base64.b64encode(value).decode("ascii")


@pytest.fixture
def vault_context(db):
    organization = Organization.objects.create(name="Vault", slug=f"vault-{uuid4()}")
    actor = get_user_model().objects.create_user(username=f"vault-{uuid4()}")
    context = TokenStoreContext(
        organization_id=organization.id,
        actor_id=actor.id,
        platform_code="FACEBOOK",
        attempt_id=uuid4(),
    )
    resolver = FixtureSecretResolver({"fixture://vault-key": key()})
    store = EncryptedDatabaseTokenStore(
        secret_resolver=resolver,
        key_reference="fixture://vault-key",
        key_version="v1",
        clock=timezone.now,
    )
    return store, context


@pytest.mark.django_db
def test_round_trip_uses_random_authenticated_ciphertext_without_plaintext(vault_context) -> None:
    store, context = vault_context
    token = OAuthTokenSet(
        access_token="fixture-access-fragment",
        refresh_token="fixture-refresh-fragment",
        token_type="Bearer",
        provider_scopes=("pages_manage_posts",),
        expires_at=timezone.now() + timedelta(hours=1),
    )

    first = store.store(token, context)
    second = store.store(token, context)
    rows = list(EncryptedOAuthCredential.objects.order_by("created_at"))

    assert first != second
    assert rows[0].nonce != rows[1].nonce
    persisted = b"|".join(bytes(row.ciphertext) + bytes(row.nonce) for row in rows)
    assert b"fixture-access-fragment" not in persisted
    assert b"fixture-refresh-fragment" not in persisted
    resolved = store.resolve(first)
    assert resolved.access_token == "fixture-access-fragment"
    assert resolved.refresh_token == "fixture-refresh-fragment"
    assert resolved.token_type == "Bearer"
    assert resolved.provider_scopes == ("pages_manage_posts",)
    assert "fixture-access-fragment" not in repr(resolved)


@pytest.mark.django_db
def test_ciphertext_is_bound_to_tenant_platform_attempt_and_reference(vault_context) -> None:
    store, context = vault_context
    reference = store.store(OAuthTokenSet(access_token="fixture-access"), context)
    row = EncryptedOAuthCredential.objects.get(reference=reference)

    row.platform_code = "INSTAGRAM"
    row.save(update_fields=["platform_code"])

    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve(reference)


@pytest.mark.django_db
def test_tampering_wrong_key_version_expiry_and_disconnect_fail_closed(vault_context) -> None:
    store, context = vault_context
    reference = store.store(
        OAuthTokenSet(
            access_token="fixture-access",
            expires_at=timezone.now() + timedelta(hours=1),
        ),
        context,
    )
    row = EncryptedOAuthCredential.objects.get(reference=reference)
    original = bytes(row.ciphertext)
    row.ciphertext = bytes([original[0] ^ 1]) + original[1:]
    row.save(update_fields=["ciphertext"])
    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve(reference)

    expired = store.store(
        OAuthTokenSet(
            access_token="fixture-expired",
            expires_at=timezone.now() - timedelta(seconds=1),
        ),
        replace(context, attempt_id=uuid4()),
    )
    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve(expired)

    active = store.store(
        OAuthTokenSet(access_token="fixture-delete"),
        replace(context, attempt_id=uuid4()),
    )
    store.delete(active)
    deleted = EncryptedOAuthCredential.objects.get(reference=active)
    assert deleted.status == EncryptedOAuthCredential.Status.DISCONNECTED
    assert bytes(deleted.ciphertext) == b""
    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve(active)

    version_mismatch = store.store(
        OAuthTokenSet(access_token="fixture-version"),
        replace(context, attempt_id=uuid4()),
    )
    wrong_resolver = FixtureSecretResolver({"fixture://wrong": key(b"W" * 32)})
    wrong_store = EncryptedDatabaseTokenStore(
        secret_resolver=wrong_resolver,
        key_reference="fixture://wrong",
        key_version="v2",
        clock=timezone.now,
    )
    with pytest.raises(ConnectorConfigurationRequired):
        wrong_store.resolve(version_mismatch)


@pytest.mark.django_db
def test_bind_selects_only_requested_candidate_and_invalidates_bundle(vault_context) -> None:
    store, context = vault_context
    bundle = ProviderCredentialBundle(
        primary=OAuthTokenSet(access_token="fixture-primary"),
        candidate_tokens={
            "candidate-a": OAuthTokenSet(access_token="fixture-page-a"),
            "candidate-b": OAuthTokenSet(access_token="fixture-page-b"),
        },
        issued_at=timezone.now(),
    )
    bundle_reference = store.store(bundle, context)

    bound_reference = store.bind(bundle_reference, "candidate-a")

    assert bound_reference != bundle_reference
    assert store.resolve(bound_reference).access_token == "fixture-page-a"
    with pytest.raises(ConnectorConfigurationRequired):
        store.resolve(bundle_reference)
    persisted = b"".join(
        bytes(row.ciphertext) for row in EncryptedOAuthCredential.objects.all()
    )
    assert b"fixture-page-b" not in persisted


@pytest.mark.django_db
def test_bind_failure_keeps_original_bundle_available(vault_context) -> None:
    store, context = vault_context
    bundle = ProviderCredentialBundle(
        primary=OAuthTokenSet(access_token="fixture-primary"),
        candidate_tokens={"candidate-a": OAuthTokenSet(access_token="fixture-page-a")},
        issued_at=timezone.now(),
    )
    reference = store.store(bundle, context)

    with pytest.raises(ConnectorConfigurationRequired):
        store.bind(reference, "missing")

    assert EncryptedOAuthCredential.objects.get(reference=reference).status == (
        EncryptedOAuthCredential.Status.ACTIVE
    )
