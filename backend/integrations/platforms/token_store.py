from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .base import ConnectorConfigurationRequired


@dataclass(frozen=True)
class OAuthTokenSet:
    access_token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class TokenStoreContext:
    organization_id: UUID
    actor_id: UUID
    platform_code: str
    attempt_id: UUID


class TokenStore(Protocol):
    def store(self, credential_bundle: object, context: TokenStoreContext) -> str: ...

    def resolve(self, reference: str) -> OAuthTokenSet: ...

    def bind(self, reference: str, candidate_id: str) -> str: ...

    def delete(self, reference: str) -> None: ...


class DisabledTokenStore:
    def store(self, credential_bundle: object, context: TokenStoreContext) -> str:
        del credential_bundle, context
        raise ConnectorConfigurationRequired("Official token storage is not configured.")

    def resolve(self, reference: str) -> OAuthTokenSet:
        del reference
        raise ConnectorConfigurationRequired("Official token storage is not configured.")

    def bind(self, reference: str, candidate_id: str) -> str:
        del reference, candidate_id
        raise ConnectorConfigurationRequired("Official token storage is not configured.")

    def delete(self, reference: str) -> None:
        del reference
        raise ConnectorConfigurationRequired("Official token storage is not configured.")
