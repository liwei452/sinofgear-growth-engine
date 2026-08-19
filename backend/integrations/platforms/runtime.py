from __future__ import annotations

import http.client
import ipaddress
import json
import socket
from dataclasses import dataclass
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPSHandler,
    HTTPRedirectHandler,
    Request,
    build_opener,
    urlopen,
)

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


class _NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects instead of silently following them to a new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, msg, headers, fp)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a pinned, already-validated IP while keeping the host for SNI."""

    def __init__(self, hostname, port, pinned_ip, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, context=None, **kwargs):
        super().__init__(hostname, port, timeout=timeout, context=context, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address,
        )
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, pinned_ip):
        self._pinned_ip = pinned_ip
        super().__init__()

    def https_open(self, req):
        return self.do_open(self._connect, req)

    def _connect(self, host, timeout):
        return _PinnedHTTPSConnection(
            host, 443, self._pinned_ip, timeout=timeout, context=self._context,
        )


class UrlMediaLoader:
    def __init__(self, opener=None, resolver=socket.getaddrinfo):
        self._opener = opener
        self._resolver = resolver

    def _resolve_public_ip(self, hostname: str) -> str:
        try:
            infos = self._resolver(hostname, 443)
        except socket.gaierror as error:
            raise ValueError("YouTube media host could not be resolved.") from error
        pinned = None
        for info in infos:
            address = ipaddress.ip_address(info[4][0])
            if not address.is_global:
                raise ValueError(
                    "YouTube media host must resolve to a public address."
                )
            if pinned is None:
                pinned = str(address)
        if pinned is None:
            raise ValueError("YouTube media host could not be resolved.")
        return pinned

    def load(self, media_url: str, max_bytes: int) -> bytes:
        parsed = urlsplit(media_url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("YouTube media must be a public HTTPS URL.")
        if not parsed.hostname:
            raise ValueError("YouTube media URL must include a host.")
        pinned_ip = self._resolve_public_ip(parsed.hostname)
        request = Request(media_url, headers={"User-Agent": "SinofGear/1.0"}, method="GET")
        opener = self._opener or build_opener(_PinnedHTTPSHandler(pinned_ip), _NoRedirectHandler())
        if self._opener is None:
            response = opener.open(request, timeout=60)
        else:
            response = opener(request, timeout=60)
        with response:
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("YouTube media exceeds the size limit.")
        return data


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
        youtube_media_loader=UrlMediaLoader(),
    )
