from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .token_store import OAuthTokenSet


class ProviderAuthorizationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("平台账号连接暂时无法完成，请按提示重试。")


@dataclass(frozen=True)
class AuthorizationCompletion:
    code: str = field(repr=False)
    redirect_uri: str
    pkce_reference: str = field(default="", repr=False)


@dataclass(frozen=True)
class ManagedPublishingAccount:
    candidate_id: str
    external_id: str
    display_name: str
    channel: str
    capabilities: tuple[str, ...]
    publication_mode: str
    discovered_at: datetime


@dataclass(frozen=True)
class ProviderCredentialBundle:
    primary: OAuthTokenSet = field(repr=False)
    candidate_tokens: dict[str, OAuthTokenSet] = field(repr=False)
    issued_at: datetime


class ProviderAuthorizationAdapter(Protocol):
    def complete(
        self, request: AuthorizationCompletion,
    ) -> tuple[ProviderCredentialBundle, list[ManagedPublishingAccount], tuple[str, ...]]: ...


def stable_candidate_id(channel: str, external_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"sinofgear:{channel}:{external_id}"))


def normalized_failure(status_code: int, *, during_exchange: bool = False) -> ProviderAuthorizationError:
    if status_code == 401:
        return ProviderAuthorizationError("REAUTHORIZATION_REQUIRED")
    if status_code >= 500 or status_code == 429:
        return ProviderAuthorizationError("PROVIDER_UNAVAILABLE")
    return ProviderAuthorizationError(
        "AUTHORIZATION_REJECTED" if during_exchange else "INSUFFICIENT_CAPABILITY"
    )

