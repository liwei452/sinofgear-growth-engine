from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .base import ConnectorConfigurationRequired


@dataclass(frozen=True)
class OAuthTokenSet:
    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None


class TokenStore(Protocol):
    def resolve(self, reference: str) -> OAuthTokenSet: ...


class DisabledTokenStore:
    def resolve(self, reference: str) -> OAuthTokenSet:
        del reference
        raise ConnectorConfigurationRequired("Official token storage is not configured.")
