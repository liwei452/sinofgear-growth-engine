from .base import ConnectorConfigurationRequired


class AuthorizationAdapterRegistry:
    def __init__(self, adapters=None):
        self.adapters = dict(adapters or {})

    def resolve(self, platform_code: str):
        provider_code = "META" if platform_code in {"FACEBOOK", "INSTAGRAM"} else platform_code
        adapter = self.adapters.get(provider_code)
        if adapter is None:
            raise ConnectorConfigurationRequired("Official account authorization is not configured.")
        return adapter
