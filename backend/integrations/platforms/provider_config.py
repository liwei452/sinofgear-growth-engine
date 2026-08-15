from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


SUPPORTED_PROVIDERS = ("META", "LINKEDIN", "TIKTOK", "YOUTUBE")
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class ProviderConfigurationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        message = (
            "Social provider configuration is missing a required scope."
            if code == "YOUTUBE_REQUIRED_SCOPE"
            else "Social provider configuration is incomplete or unsafe."
        )
        super().__init__(message)


@dataclass(frozen=True)
class SocialProviderConfig:
    code: str
    enabled: bool = False
    client_id: str = ""
    client_secret_reference: str = field(default="", repr=False)
    redirect_uri: str = ""
    scopes: tuple[str, ...] = ()
    api_version: str = ""
    audited: bool = False


def _normalized_origin(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise ProviderConfigurationError("INVALID_ALLOWED_ORIGIN")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProviderConfigurationError("INVALID_ALLOWED_ORIGIN")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _callback_channels(code: str) -> tuple[str, ...]:
    return ("FACEBOOK", "INSTAGRAM") if code == "META" else (code,)


def _validate_callback(
    code: str, redirect_uri: str, *, allowed_origins: set[str], test_mode: bool,
) -> None:
    try:
        parsed = urlsplit(redirect_uri)
        origin = _normalized_origin(f"{parsed.scheme}://{parsed.netloc}")
    except (TypeError, ValueError, ProviderConfigurationError) as error:
        raise ProviderConfigurationError("INVALID_CALLBACK") from error
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderConfigurationError("INVALID_CALLBACK")
    if parsed.scheme.lower() != "https" and not (
        test_mode and parsed.scheme.lower() == "http"
    ):
        raise ProviderConfigurationError("INVALID_CALLBACK")
    allowed_paths = {
        f"/api/v1/platform-connections/{channel}/callback"
        for channel in _callback_channels(code)
    }
    if origin not in allowed_origins or parsed.path not in allowed_paths:
        raise ProviderConfigurationError("INVALID_CALLBACK")


def load_provider_configs(
    raw: dict, *, allowed_origins: tuple[str, ...], test_mode: bool = False,
) -> dict[str, SocialProviderConfig]:
    unknown = set(raw) - set(SUPPORTED_PROVIDERS)
    if unknown:
        raise ProviderConfigurationError("UNKNOWN_PROVIDER")
    origins = {_normalized_origin(value) for value in allowed_origins}
    configs: dict[str, SocialProviderConfig] = {}
    for code in SUPPORTED_PROVIDERS:
        source = raw.get(code, {})
        enabled = source.get("enabled") is True
        config = SocialProviderConfig(
            code=code,
            enabled=enabled,
            client_id=str(source.get("client_id", "")).strip(),
            client_secret_reference=str(
                source.get("client_secret_reference", "")
            ).strip(),
            redirect_uri=str(source.get("redirect_uri", "")).strip(),
            scopes=tuple(str(scope).strip() for scope in source.get("scopes", ()) if str(scope).strip()),
            api_version=str(source.get("api_version", "")).strip(),
            audited=source.get("audited") is True,
        )
        if enabled:
            if not config.client_id or not config.client_secret_reference:
                raise ProviderConfigurationError("MISSING_CREDENTIAL_REFERENCE")
            _validate_callback(
                code,
                config.redirect_uri,
                allowed_origins=origins,
                test_mode=test_mode,
            )
            if code == "YOUTUBE" and YOUTUBE_UPLOAD_SCOPE not in config.scopes:
                raise ProviderConfigurationError("YOUTUBE_REQUIRED_SCOPE")
            if code == "LINKEDIN" and not config.api_version:
                raise ProviderConfigurationError("LINKEDIN_API_VERSION_REQUIRED")
        configs[code] = config
    return configs
