from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Mapping, Protocol

from .base import ConnectorConfigurationRequired


@dataclass(frozen=True)
class SecretValue:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return "[REDACTED]"

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"


class SecretResolver(Protocol):
    def resolve(self, reference: str) -> SecretValue: ...


class DisabledSecretResolver:
    def resolve(self, reference: str) -> SecretValue:
        del reference
        raise ConnectorConfigurationRequired("Social provider secret is not configured.")

    def __repr__(self) -> str:
        return "DisabledSecretResolver()"


class FixtureSecretResolver:
    def __init__(self, values: Mapping[str, str]):
        if any(not key.startswith("fixture://") for key in values):
            raise ValueError("Fixture resolver accepts fixture-owned references only.")
        self._values = dict(values)

    def resolve(self, reference: str) -> SecretValue:
        try:
            value = self._values[reference]
        except KeyError as error:
            raise ConnectorConfigurationRequired(
                "Fixture social provider secret is unavailable."
            ) from error
        return SecretValue(value)

    def __repr__(self) -> str:
        return f"FixtureSecretResolver(count={len(self._values)})"


class EnvironmentSecretResolver:
    _reference = re.compile(r"env://([A-Z][A-Z0-9_]{0,127})\Z")

    def resolve(self, reference: str) -> SecretValue:
        match = self._reference.fullmatch(reference)
        value = os.environ.get(match.group(1), "") if match else ""
        if not value:
            raise ConnectorConfigurationRequired(
                "Environment-backed social provider secret is unavailable."
            )
        return SecretValue(value)

    def __repr__(self) -> str:
        return "EnvironmentSecretResolver()"
