import base64
from io import StringIO
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.models import EncryptedOAuthCredential
from integrations.platforms.encrypted_token_store import EncryptedDatabaseTokenStore
from integrations.platforms.secret_resolver import EnvironmentSecretResolver
from integrations.platforms.token_store import OAuthTokenSet, TokenStoreContext


def encoded(byte: bytes) -> str:
    return base64.b64encode(byte * 32).decode("ascii")


def create_row(organization, actor, *, suffix: str, monkeypatch):
    monkeypatch.setenv("SOCIAL_OLD_KEY", encoded(b"O"))
    store = EncryptedDatabaseTokenStore(
        secret_resolver=EnvironmentSecretResolver(),
        key_reference="env://SOCIAL_OLD_KEY",
        key_version="v1",
        clock=timezone.now,
    )
    reference = store.store(
        OAuthTokenSet(access_token=f"fixture-access-{suffix}"),
        TokenStoreContext(organization.id, actor.id, "FACEBOOK", uuid4()),
    )
    return reference


@pytest.mark.django_db
@override_settings(SOCIAL_OAUTH_TOKEN_KEY_REFERENCE="env://SOCIAL_OLD_KEY")
def test_rotation_dry_run_then_rewrites_with_fresh_nonce_and_is_idempotent(monkeypatch) -> None:
    organization = Organization.objects.create(name="Rotate", slug=f"rotate-{uuid4()}")
    actor = get_user_model().objects.create_user(username=f"rotate-{uuid4()}")
    reference = create_row(organization, actor, suffix="safe", monkeypatch=monkeypatch)
    monkeypatch.setenv("SOCIAL_NEW_KEY", encoded(b"N"))
    before = EncryptedOAuthCredential.objects.get(reference=reference)
    old_nonce = bytes(before.nonce)
    output = StringIO()

    call_command(
        "rotate_social_oauth_keys",
        from_version="v1",
        to_version="v2",
        new_key_reference="env://SOCIAL_NEW_KEY",
        dry_run=True,
        stdout=output,
    )
    before.refresh_from_db()
    assert before.key_version == "v1"

    call_command(
        "rotate_social_oauth_keys",
        from_version="v1",
        to_version="v2",
        new_key_reference="env://SOCIAL_NEW_KEY",
        stdout=output,
    )
    before.refresh_from_db()
    assert before.key_version == "v2"
    assert bytes(before.nonce) != old_nonce
    call_command(
        "rotate_social_oauth_keys",
        from_version="v1",
        to_version="v2",
        new_key_reference="env://SOCIAL_NEW_KEY",
        stdout=output,
    )
    assert "fixture-access-safe" not in output.getvalue()


@pytest.mark.django_db
@override_settings(SOCIAL_OAUTH_TOKEN_KEY_REFERENCE="env://SOCIAL_OLD_KEY")
def test_rotation_can_be_bounded_to_one_organization(monkeypatch) -> None:
    first = Organization.objects.create(name="First", slug=f"first-{uuid4()}")
    second = Organization.objects.create(name="Second", slug=f"second-{uuid4()}")
    actor = get_user_model().objects.create_user(username=f"rotate-org-{uuid4()}")
    first_ref = create_row(first, actor, suffix="first", monkeypatch=monkeypatch)
    second_ref = create_row(second, actor, suffix="second", monkeypatch=monkeypatch)
    monkeypatch.setenv("SOCIAL_NEW_KEY", encoded(b"N"))

    call_command(
        "rotate_social_oauth_keys",
        from_version="v1",
        to_version="v2",
        new_key_reference="env://SOCIAL_NEW_KEY",
        organization=str(first.id),
    )

    assert EncryptedOAuthCredential.objects.get(reference=first_ref).key_version == "v2"
    assert EncryptedOAuthCredential.objects.get(reference=second_ref).key_version == "v1"


@pytest.mark.django_db
@override_settings(SOCIAL_OAUTH_TOKEN_KEY_REFERENCE="env://SOCIAL_OLD_KEY")
def test_wrong_old_key_fails_without_changing_ciphertext(monkeypatch) -> None:
    organization = Organization.objects.create(name="Wrong", slug=f"wrong-{uuid4()}")
    actor = get_user_model().objects.create_user(username=f"wrong-{uuid4()}")
    reference = create_row(organization, actor, suffix="wrong", monkeypatch=monkeypatch)
    row = EncryptedOAuthCredential.objects.get(reference=reference)
    original = bytes(row.ciphertext)
    monkeypatch.setenv("SOCIAL_OLD_KEY", encoded(b"X"))
    monkeypatch.setenv("SOCIAL_NEW_KEY", encoded(b"N"))

    with pytest.raises(Exception, match="rotation failed"):
        call_command(
            "rotate_social_oauth_keys",
            from_version="v1",
            to_version="v2",
            new_key_reference="env://SOCIAL_NEW_KEY",
        )

    row.refresh_from_db()
    assert row.key_version == "v1"
    assert bytes(row.ciphertext) == original
