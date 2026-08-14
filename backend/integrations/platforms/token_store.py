from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from .base import ConnectorConfigurationRequired


@dataclass(frozen=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None


@dataclass(frozen=True)
class TokenStoreContext:
    organization_id: UUID
    actor_id: UUID
    platform_code: str
    attempt_id: UUID


class TokenStore(Protocol):
    def store(self, token_set: OAuthTokenSet, context: TokenStoreContext) -> str: ...

    def resolve(self, reference: str) -> OAuthTokenSet: ...

    def delete(self, reference: str) -> None: ...


class DisabledTokenStore:
    def store(self, token_set: OAuthTokenSet, context: TokenStoreContext) -> str:
        del token_set, context
        raise ConnectorConfigurationRequired("Official token storage is not configured.")

    def resolve(self, reference: str) -> OAuthTokenSet:
        del reference
        raise ConnectorConfigurationRequired("Official token storage is not configured.")

    def delete(self, reference: str) -> None:
        del reference
        raise ConnectorConfigurationRequired("Official token storage is not configured.")
