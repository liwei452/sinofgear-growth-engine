from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from .authorization_registry import AuthorizationAdapterRegistry
from .encrypted_token_store import EncryptedDatabaseTokenStore
from .linkedin import LinkedInConnector
from .linkedin_authorization import LinkedInAuthorizationAdapter
from .meta import MetaConnector
from .meta_authorization import MetaAuthorizationAdapter
from .provider_config import (
    ProviderConfigurationError,
    SocialProviderConfig,
    load_provider_configs,
)
from .registry import ConnectorRegistry
from .secret_resolver import EnvironmentSecretResolver, SecretResolver
from .tiktok import TikTokConnector
from .tiktok_authorization import TikTokAuthorizationAdapter
from .token_store import DisabledTokenStore, TokenStore
from .transport import HttpResponse
from .youtube import YouTubeConnector
from .youtube_authorization import YouTubeAuthorizationAdapter


@dataclass(frozen=True)
class ProviderReadiness:
    authorization_ready: bool
    publishing_ready: bool
    status: str
    safe_reason: str
    publication_mode: str = "UNAVAILABLE"
    public_direct_post_ready: bool = False


@dataclass(frozen=True, repr=False)
class SocialProviderRuntime:
    authorization_registry: AuthorizationAdapterRegistry
    connector_registry: ConnectorRegistry
    token_store: TokenStore
    readiness: dict[str, ProviderReadiness]

    def __repr__(self) -> str:
        ready = sorted(
            code for code, value in self.readiness.items() if value.authorization_ready
        )
        return f"SocialProviderRuntime(authorization_ready={ready!r})"


class UrllibPlatformTransport:
    max_response_bytes = 1_000_000

    def request(
        self, method, url, *, headers, json: dict | None, timeout_seconds,
        data: bytes | None = None,
    ):
        data = data if data is not None else (None if json is None else json_dumps(json))
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=min(max(int(timeout_seconds), 1), 30)) as response:  # noqa: S310
                raw = response.read(self.max_response_bytes + 1)
                status_code = response.status
                response_headers = dict(response.headers.items())
        except HTTPError as error:
            raw = error.read(self.max_response_bytes + 1)
            status_code = error.code
            response_headers = dict(error.headers.items()) if error.headers else {}
        except (URLError, TimeoutError) as error:
            raise TimeoutError("Social provider request failed.") from error
        if len(raw) > self.max_response_bytes:
            raise TimeoutError("Social provider response exceeded the size limit.")
        try:
            body = json_loads(raw)
        except (UnicodeDecodeError, JSONDecodeError):
            body = {}
        return HttpResponse(status_code=status_code, json_body=body, headers=response_headers)


def json_loads(raw: bytes) -> dict:
    value = json.loads(raw.decode("utf-8")) if raw else {}
    return value if isinstance(value, dict) else {}


def json_dumps(value: dict) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _unavailable() -> ProviderReadiness:
    return ProviderReadiness(
        False,
        False,
        "CONFIGURATION_REQUIRED",
        "平台连接尚未完成服务器配置。",
    )


def build_social_provider_runtime(
    configs: dict[str, SocialProviderConfig],
    secret_resolver: SecretResolver,
    token_store: TokenStore,
    transport_factory,
    youtube_media_loader=None,
) -> SocialProviderRuntime:
    adapters = {}
    connectors = {}
    readiness = {code: _unavailable() for code in ("FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE")}
    token_store_ready = not isinstance(token_store, DisabledTokenStore)
    for provider_code in ("META", "LINKEDIN", "TIKTOK", "YOUTUBE"):
        config = configs.get(provider_code)
        if config is None or not config.enabled or not token_store_ready:
            continue
        try:
            client_secret = secret_resolver.resolve(
                config.client_secret_reference
            ).reveal()
        except Exception:
            continue
        transport = transport_factory(provider_code)
        if provider_code == "META":
            graph_url = f"https://graph.facebook.com/{config.api_version or 'v23.0'}"
            adapter = MetaAuthorizationAdapter(
                transport=transport,
                client_id=config.client_id,
                client_secret=client_secret,
                graph_base_url=graph_url,
            )
            adapters["META"] = adapter
            if config.audited:
                connector = MetaConnector(
                    transport=transport, token_store=token_store, graph_base_url=graph_url
                )
                connectors.update({"FACEBOOK": connector, "INSTAGRAM": connector})
            state = ProviderReadiness(
                True,
                config.audited,
                "CONNECTED" if config.audited else "WAITING_PLATFORM_REVIEW",
                "可连接账号。" if config.audited else "可连接账号，发布权限仍等待平台审核。",
                "PUBLIC" if config.audited else "UNAVAILABLE",
                config.audited,
            )
            readiness["FACEBOOK"] = state
            readiness["INSTAGRAM"] = state
        elif provider_code == "LINKEDIN":
            adapters["LINKEDIN"] = LinkedInAuthorizationAdapter(
                transport=transport,
                client_id=config.client_id,
                client_secret=client_secret,
                api_version=config.api_version,
            )
            if config.audited:
                connectors["LINKEDIN"] = LinkedInConnector(
                    transport=transport,
                    token_store=token_store,
                    api_version=config.api_version,
                )
            readiness["LINKEDIN"] = ProviderReadiness(
                True,
                config.audited,
                "CONNECTED" if config.audited else "WAITING_PLATFORM_REVIEW",
                "可连接账号。" if config.audited else "可连接账号，发布权限仍等待平台审核。",
                "PUBLIC" if config.audited else "UNAVAILABLE",
                config.audited,
            )
        elif provider_code == "TIKTOK":
            adapters["TIKTOK"] = TikTokAuthorizationAdapter(
                transport=transport,
                client_key=config.client_id,
                client_secret=client_secret,
                client_audited=config.audited,
            )
            connectors["TIKTOK"] = TikTokConnector(
                transport=transport,
                token_store=token_store,
                client_audited=config.audited,
            )
            readiness["TIKTOK"] = ProviderReadiness(
                True,
                True,
                "CONNECTED" if config.audited else "PRIVATE_ONLY",
                "可公开发布。" if config.audited else "可上传，但当前仅支持私密发布。",
                "PUBLIC" if config.audited else "PRIVATE_ONLY",
                config.audited,
            )
        else:
            adapters["YOUTUBE"] = YouTubeAuthorizationAdapter(
                transport=transport,
                client_id=config.client_id,
                client_secret=client_secret,
            )
            publishing_ready = config.audited and youtube_media_loader is not None
            if publishing_ready:
                connectors["YOUTUBE"] = YouTubeConnector(
                    transport=transport,
                    token_store=token_store,
                    media_loader=youtube_media_loader,
                )
            readiness["YOUTUBE"] = ProviderReadiness(
                True,
                publishing_ready,
                "CONNECTED" if publishing_ready else "WAITING_PLATFORM_REVIEW",
                "可上传视频。" if publishing_ready else "可连接账号，视频上传仍未激活。",
                "UPLOAD" if publishing_ready else "UNAVAILABLE",
                False,
            )
    return SocialProviderRuntime(
        AuthorizationAdapterRegistry(adapters),
        ConnectorRegistry(official_connectors=connectors),
        token_store,
        readiness,
    )


def get_social_provider_runtime() -> SocialProviderRuntime:
    try:
        configs = load_provider_configs(
            settings.SOCIAL_PROVIDER_CONFIG,
            allowed_origins=settings.SOCIAL_OAUTH_ALLOWED_ORIGINS,
            test_mode=False,
        )
    except ProviderConfigurationError:
        configs = load_provider_configs({}, allowed_origins=())
    resolver = EnvironmentSecretResolver()
    key_reference = settings.SOCIAL_OAUTH_TOKEN_KEY_REFERENCE
    token_store = (
        EncryptedDatabaseTokenStore(
            secret_resolver=resolver,
            key_reference=key_reference,
            key_version=settings.SOCIAL_OAUTH_TOKEN_KEY_VERSION,
            clock=timezone.now,
        )
        if key_reference
        else DisabledTokenStore()
    )
    return build_social_provider_runtime(
        configs,
        resolver,
        token_store,
        lambda _code: UrllibPlatformTransport(),
    )
