from types import SimpleNamespace

import pytest

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.provider_config import load_provider_configs
from integrations.platforms.runtime import build_social_provider_runtime
from integrations.platforms.secret_resolver import FixtureSecretResolver
from integrations.platforms.token_store import OAuthTokenSet


ORIGIN = "https://app.sinfogear.com"


class NoNetworkTransport:
    def __init__(self):
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("runtime construction must not contact a provider")


class FixtureTokenStore:
    def store(self, credential_bundle, context):
        return "fixture://bundle"

    def resolve(self, reference):
        return OAuthTokenSet(access_token="fixture-token")

    def bind(self, reference, candidate_id):
        return "fixture://bound"

    def delete(self, reference):
        return None


def config(code: str, *, audited=True, scopes=("publish",)):
    callback = "FACEBOOK" if code == "META" else code
    return {
        "enabled": True,
        "client_id": f"{code.lower()}-public-id",
        "client_secret_reference": f"fixture://{code.lower()}",
        "redirect_uri": f"{ORIGIN}/api/v1/platform-connections/{callback}/callback",
        "scopes": list(scopes),
        "api_version": "202608" if code == "LINKEDIN" else "v3",
        "audited": audited,
    }


def build(raw, secrets, *, youtube_media_loader=None):
    configs = load_provider_configs(raw, allowed_origins=(ORIGIN,))
    transports = {}

    def transport_factory(code):
        transports.setdefault(code, NoNetworkTransport())
        return transports[code]

    runtime = build_social_provider_runtime(
        configs,
        FixtureSecretResolver(secrets),
        FixtureTokenStore(),
        transport_factory,
        youtube_media_loader=youtube_media_loader,
    )
    return runtime, transports


def test_disabled_and_missing_secret_providers_fail_closed_without_network() -> None:
    runtime, transports = build({}, {})
    assert transports == {}
    with pytest.raises(ConnectorConfigurationRequired):
        runtime.authorization_registry.resolve("FACEBOOK")
    assert runtime.readiness["FACEBOOK"].status == "CONFIGURATION_REQUIRED"
    assert runtime.readiness["YOUTUBE"].authorization_ready is False


def test_meta_registers_two_channels_with_one_authorization_adapter() -> None:
    runtime, transports = build(
        {"META": config("META")}, {"fixture://meta": "fixture-meta-secret"}
    )
    facebook = runtime.authorization_registry.resolve("FACEBOOK")
    instagram = runtime.authorization_registry.resolve("INSTAGRAM")

    assert facebook is instagram
    assert runtime.connector_registry.official_connectors["FACEBOOK"] is (
        runtime.connector_registry.official_connectors["INSTAGRAM"]
    )
    assert transports["META"].calls == []
    assert "fixture-meta-secret" not in repr(runtime)


def test_authorization_can_be_ready_while_platform_review_blocks_publishing() -> None:
    runtime, _ = build(
        {"LINKEDIN": config("LINKEDIN", audited=False)},
        {"fixture://linkedin": "fixture-linkedin-secret"},
    )
    readiness = runtime.readiness["LINKEDIN"]
    assert readiness.authorization_ready is True
    assert readiness.publishing_ready is False
    assert readiness.status == "WAITING_PLATFORM_REVIEW"


def test_tiktok_unaudited_runtime_is_private_only_not_public_direct_post() -> None:
    runtime, _ = build(
        {"TIKTOK": config("TIKTOK", audited=False)},
        {"fixture://tiktok": "fixture-tiktok-secret"},
    )
    readiness = runtime.readiness["TIKTOK"]
    assert readiness.authorization_ready is True
    assert readiness.publishing_ready is True
    assert readiness.public_direct_post_ready is False
    assert readiness.publication_mode == "PRIVATE_ONLY"
    account = SimpleNamespace(
        platform=SimpleNamespace(code="TIKTOK"),
        connector_metadata={"connection_kind": "official_oauth"},
    )
    assert runtime.connector_registry.resolve(account) is not None


def test_youtube_authorization_and_upload_readiness_are_separate() -> None:
    raw = {
        "YOUTUBE": config(
            "YOUTUBE",
            scopes=("https://www.googleapis.com/auth/youtube.upload",),
        )
    }
    without_media, _ = build(
        raw, {"fixture://youtube": "fixture-youtube-secret"}
    )
    with_media, transports = build(
        raw,
        {"fixture://youtube": "fixture-youtube-secret"},
        youtube_media_loader=object(),
    )

    assert without_media.readiness["YOUTUBE"].authorization_ready is True
    assert without_media.readiness["YOUTUBE"].publishing_ready is False
    assert with_media.readiness["YOUTUBE"].publishing_ready is True
    assert transports["YOUTUBE"].calls == []


def test_runtime_registers_one_buffer_connector_without_network() -> None:
    runtime, transports = build({}, {})
    account = SimpleNamespace(
        provider="BUFFER",
        platform=SimpleNamespace(code="LINKEDIN"),
        connector_metadata={},
    )

    connector = runtime.connector_registry.resolve(account)

    assert connector is runtime.connector_registry.provider_connectors["BUFFER"]
    assert transports == {}
