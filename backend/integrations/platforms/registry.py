from .mock import mock_connector_factory


CONNECTOR_FACTORIES = {"mock": mock_connector_factory}


def get_connector(code, account):
    try:
        factory = CONNECTOR_FACTORIES[code]
    except KeyError as exc:
        raise LookupError("Publishing connector is not registered.") from exc
    return factory(account)
