from __future__ import annotations

import base64
import binascii
import json
import secrets
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.db import transaction

from apps.platforms.models import EncryptedOAuthCredential

from .authorization import ProviderCredentialBundle
from .base import ConnectorConfigurationRequired
from .secret_resolver import SecretResolver
from .token_store import OAuthTokenSet, TokenStoreContext


class EncryptedDatabaseTokenStore:
    def __init__(self, *, secret_resolver: SecretResolver, key_reference: str, key_version: str, clock):
        self._secret_resolver = secret_resolver
        self._key_reference = key_reference
        self.key_version = key_version
        self._clock = clock

    def __repr__(self) -> str:
        return f"EncryptedDatabaseTokenStore(key_version={self.key_version!r})"

    def _key(self) -> bytes:
        try:
            encoded = self._secret_resolver.resolve(self._key_reference).reveal()
            key = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError, binascii.Error) as error:
            raise ConnectorConfigurationRequired(
                "Social credential encryption is not configured."
            ) from error
        if len(key) != 32:
            raise ConnectorConfigurationRequired(
                "Social credential encryption is not configured."
            )
        return key

    @staticmethod
    def _associated_data(row: EncryptedOAuthCredential) -> bytes:
        return json.dumps(
            {
                "reference": row.reference,
                "organization_id": str(row.organization_id),
                "actor_identifier": row.actor_identifier,
                "platform_code": row.platform_code,
                "connection_attempt_id": str(row.connection_attempt_id),
                "account_binding": row.account_binding,
                "key_version": row.key_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _token_payload(token: OAuthTokenSet) -> dict:
        return {
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "token_type": token.token_type,
            "provider_scopes": list(token.provider_scopes),
        }

    @staticmethod
    def _token_from_payload(payload: dict) -> OAuthTokenSet:
        expires_at = payload.get("expires_at")
        return OAuthTokenSet(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload.get("refresh_token", "")),
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            token_type=str(payload.get("token_type", "Bearer")),
            provider_scopes=tuple(str(value) for value in payload.get("provider_scopes", ())),
        )

    def _serialize(self, credential_bundle: object) -> tuple[dict, datetime | None]:
        if isinstance(credential_bundle, OAuthTokenSet):
            return {"kind": "token", "token": self._token_payload(credential_bundle)}, credential_bundle.expires_at
        if isinstance(credential_bundle, ProviderCredentialBundle):
            return {
                "kind": "bundle",
                "primary": self._token_payload(credential_bundle.primary),
                "candidates": {
                    key: self._token_payload(value)
                    for key, value in credential_bundle.candidate_tokens.items()
                },
                "issued_at": credential_bundle.issued_at.isoformat(),
            }, credential_bundle.primary.expires_at
        raise TypeError("Unsupported social credential bundle.")

    def _encrypt_row(self, row: EncryptedOAuthCredential, payload: dict) -> None:
        nonce = secrets.token_bytes(12)
        plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        row.nonce = nonce
        row.ciphertext = AESGCM(self._key()).encrypt(
            nonce, plaintext, self._associated_data(row)
        )

    def _decrypt_row(self, row: EncryptedOAuthCredential) -> dict:
        if row.key_version != self.key_version or row.status != EncryptedOAuthCredential.Status.ACTIVE:
            raise ConnectorConfigurationRequired("Social credential is unavailable.")
        if row.expires_at is not None and row.expires_at <= self._clock():
            raise ConnectorConfigurationRequired("Social credential is unavailable.")
        try:
            plaintext = AESGCM(self._key()).decrypt(
                bytes(row.nonce), bytes(row.ciphertext), self._associated_data(row)
            )
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidTag, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise ConnectorConfigurationRequired("Social credential is unavailable.") from error
        if not isinstance(payload, dict):
            raise ConnectorConfigurationRequired("Social credential is unavailable.")
        return payload

    def _create(
        self, *, payload: dict, context: TokenStoreContext, expires_at: datetime | None,
        account_binding: str = "",
    ) -> EncryptedOAuthCredential:
        row = EncryptedOAuthCredential(
            organization_id=context.organization_id,
            reference=secrets.token_urlsafe(48),
            actor_identifier=str(context.actor_id),
            platform_code=context.platform_code,
            connection_attempt_id=context.attempt_id,
            account_binding=account_binding,
            key_version=self.key_version,
            expires_at=expires_at,
        )
        self._encrypt_row(row, payload)
        row.save(force_insert=True)
        return row

    def store(self, credential_bundle: object, context: TokenStoreContext) -> str:
        payload, expires_at = self._serialize(credential_bundle)
        return self._create(payload=payload, context=context, expires_at=expires_at).reference

    def resolve(self, reference: str) -> OAuthTokenSet:
        try:
            row = EncryptedOAuthCredential.objects.get(reference=reference)
        except EncryptedOAuthCredential.DoesNotExist as error:
            raise ConnectorConfigurationRequired("Social credential is unavailable.") from error
        payload = self._decrypt_row(row)
        token_payload = payload.get("token") if payload.get("kind") == "token" else payload.get("primary")
        if not isinstance(token_payload, dict):
            raise ConnectorConfigurationRequired("Social credential is unavailable.")
        try:
            return self._token_from_payload(token_payload)
        except (KeyError, TypeError, ValueError) as error:
            raise ConnectorConfigurationRequired("Social credential is unavailable.") from error

    @transaction.atomic
    def bind(self, reference: str, candidate_id: str) -> str:
        try:
            row = EncryptedOAuthCredential.objects.select_for_update().get(reference=reference)
        except EncryptedOAuthCredential.DoesNotExist as error:
            raise ConnectorConfigurationRequired("Social credential is unavailable.") from error
        payload = self._decrypt_row(row)
        candidates = payload.get("candidates") if payload.get("kind") == "bundle" else None
        selected = candidates.get(candidate_id) if isinstance(candidates, dict) else None
        if not isinstance(selected, dict):
            raise ConnectorConfigurationRequired("Social credential account is unavailable.")
        token = self._token_from_payload(selected)
        context = TokenStoreContext(
            organization_id=row.organization_id,
            actor_id=row.actor_identifier,
            platform_code=row.platform_code,
            attempt_id=row.connection_attempt_id,
        )
        bound = self._create(
            payload={"kind": "token", "token": selected},
            context=context,
            expires_at=token.expires_at,
            account_binding=candidate_id,
        )
        row.status = EncryptedOAuthCredential.Status.ROTATED
        row.ciphertext = b""
        row.nonce = b""
        row.save(update_fields=["status", "ciphertext", "nonce", "updated_at"])
        return bound.reference

    @transaction.atomic
    def delete(self, reference: str) -> None:
        try:
            row = EncryptedOAuthCredential.objects.select_for_update().get(reference=reference)
        except EncryptedOAuthCredential.DoesNotExist as error:
            raise ConnectorConfigurationRequired("Social credential is unavailable.") from error
        row.status = EncryptedOAuthCredential.Status.DISCONNECTED
        row.ciphertext = b""
        row.nonce = b""
        row.disconnected_at = self._clock()
        row.save(
            update_fields=[
                "status", "ciphertext", "nonce", "disconnected_at", "updated_at",
            ]
        )
