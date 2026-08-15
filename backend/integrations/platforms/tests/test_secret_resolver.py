import pytest

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.secret_resolver import (
    DisabledSecretResolver,
    FixtureSecretResolver,
)


def test_disabled_resolver_fails_closed_without_echoing_reference() -> None:
    reference = "env://REAL_SECRET_REFERENCE"

    with pytest.raises(ConnectorConfigurationRequired) as error:
        DisabledSecretResolver().resolve(reference)

    assert reference not in str(error.value)


def test_fixture_secret_value_is_explicitly_revealed_and_always_redacted() -> None:
    value = "fixture-value-never-print"
    resolver = FixtureSecretResolver({"fixture://client": value})

    secret = resolver.resolve("fixture://client")

    assert secret.reveal() == value
    assert value not in str(secret)
    assert value not in repr(secret)
    assert value not in repr(resolver)


def test_fixture_resolver_rejects_non_fixture_references_and_unknown_values() -> None:
    with pytest.raises(ValueError):
        FixtureSecretResolver({"env://client": "fixture-value"})
    resolver = FixtureSecretResolver({"fixture://client": "fixture-value"})
    with pytest.raises(ConnectorConfigurationRequired) as error:
        resolver.resolve("fixture://missing")
    assert "fixture://missing" not in str(error.value)
