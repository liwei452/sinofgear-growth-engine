from .mock import mock_connector_factory
from .base import ConnectorConfigurationRequired
from .manual_fake import ManualPackageFakeConnector


CONNECTOR_FACTORIES = {"mock": mock_connector_factory}


def get_connector(code, account):
    try:
        factory = CONNECTOR_FACTORIES[code]
    except KeyError as exc:
        raise LookupError("Publishing connector is not registered.") from exc
    return factory(account)


class ConnectorRegistry:
    def __init__(self, *, official_connectors=None):
        self.official_connectors = dict(official_connectors or {})

    def resolve(self, account):
        metadata = account.connector_metadata if isinstance(account.connector_metadata, dict) else {}
        connection_kind = metadata.get("connection_kind")
        if not connection_kind and metadata.get("fixture") == "phase-a-e2e":
            connection_kind = "demo_fake"
        if connection_kind == "demo_fake":
            return ManualPackageFakeConnector()
        if connection_kind != "official_oauth":
            raise ConnectorConfigurationRequired("Platform account is not connected through official OAuth.")
        try:
            return self.official_connectors[account.platform.code]
        except KeyError as exc:
            raise ConnectorConfigurationRequired(
                "Official publishing connector is not configured."
            ) from exc
