import pytest

from integrations.platforms.authorization_registry import AuthorizationAdapterRegistry
from integrations.platforms.base import ConnectorConfigurationRequired


class Adapter:
    pass


def test_authorization_registry_maps_meta_channels_and_fails_closed() -> None:
    meta = Adapter()
    linkedin = Adapter()
    registry = AuthorizationAdapterRegistry({"META": meta, "LINKEDIN": linkedin})

    assert registry.resolve("FACEBOOK") is meta
    assert registry.resolve("INSTAGRAM") is meta
    assert registry.resolve("LINKEDIN") is linkedin
    with pytest.raises(ConnectorConfigurationRequired):
        registry.resolve("TIKTOK")
