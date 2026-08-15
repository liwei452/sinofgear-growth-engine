from dataclasses import asdict

import pytest

from integrations.platforms.provider_config import (
    ProviderConfigurationError,
    load_provider_configs,
)


ORIGIN = "https://app.sinfogear.com"


def raw(code: str, **overrides):
    values = {
        "enabled": True,
        "client_id": "public-client-id",
        "client_secret_reference": f"env://{code}_CLIENT_SECRET",
        "redirect_uri": f"{ORIGIN}/api/v1/platform-connections/{code}/callback",
        "scopes": ["publish"],
        "api_version": "202608",
        "audited": True,
    }
    values.update(overrides)
    return {code: values}


def test_missing_provider_entries_are_disabled_and_secret_references_are_not_repr() -> None:
    configs = load_provider_configs({}, allowed_origins=(ORIGIN,))

    assert set(configs) == {"META", "LINKEDIN", "TIKTOK", "YOUTUBE"}
    assert all(not item.enabled for item in configs.values())
    youtube = load_provider_configs(
        raw("YOUTUBE", scopes=["https://www.googleapis.com/auth/youtube.upload"]),
        allowed_origins=(ORIGIN,),
    )["YOUTUBE"]
    assert youtube.enabled is True
    assert "secret" not in repr(youtube).lower()
    assert asdict(youtube)["client_secret_reference"].startswith("env://")


@pytest.mark.parametrize("field", ["client_id", "client_secret_reference"])
def test_enabled_provider_requires_public_id_and_secret_reference(field: str) -> None:
    with pytest.raises(ProviderConfigurationError) as error:
        load_provider_configs(raw("LINKEDIN", **{field: ""}), allowed_origins=(ORIGIN,))
    assert "env://LINKEDIN_CLIENT_SECRET" not in str(error.value)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback",
        "https://user:pass@app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback",
        f"{ORIGIN}/api/v1/platform-connections/YOUTUBE/callback#fragment",
        f"{ORIGIN}/api/v1/platform-connections/TIKTOK/callback",
        "https://other.example/api/v1/platform-connections/YOUTUBE/callback",
    ],
)
def test_callback_must_be_exact_safe_https_route(redirect_uri: str) -> None:
    with pytest.raises(ProviderConfigurationError):
        load_provider_configs(
            raw(
                "YOUTUBE",
                redirect_uri=redirect_uri,
                scopes=["https://www.googleapis.com/auth/youtube.upload"],
            ),
            allowed_origins=(ORIGIN,),
        )


def test_test_mode_allows_http_testserver_but_not_a_wrong_path() -> None:
    config = load_provider_configs(
        raw(
            "LINKEDIN",
            redirect_uri="http://testserver/api/v1/platform-connections/LINKEDIN/callback",
        ),
        allowed_origins=("http://testserver",),
        test_mode=True,
    )
    assert config["LINKEDIN"].enabled


def test_meta_shared_configuration_uses_facebook_callback() -> None:
    config = load_provider_configs(
        raw(
            "META",
            redirect_uri=f"{ORIGIN}/api/v1/platform-connections/FACEBOOK/callback",
            scopes=["pages_show_list", "pages_manage_posts", "instagram_content_publish"],
        ),
        allowed_origins=(ORIGIN,),
    )
    assert config["META"].code == "META"


def test_provider_specific_metadata_and_youtube_scope_are_retained() -> None:
    config = load_provider_configs(
        {
            **raw("LINKEDIN", api_version="202608"),
            **raw("TIKTOK", audited=False, api_version=""),
            **raw(
                "YOUTUBE",
                api_version="",
                scopes=["https://www.googleapis.com/auth/youtube.upload"],
            ),
        },
        allowed_origins=(ORIGIN,),
    )
    assert config["LINKEDIN"].api_version == "202608"
    assert config["TIKTOK"].audited is False
    assert config["YOUTUBE"].scopes == (
        "https://www.googleapis.com/auth/youtube.upload",
    )


def test_youtube_requires_upload_scope() -> None:
    with pytest.raises(ProviderConfigurationError, match="required scope"):
        load_provider_configs(raw("YOUTUBE"), allowed_origins=(ORIGIN,))
