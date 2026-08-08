import pytest
from django.conf import settings

from config.settings import database_from_url


def test_runtime_database_settings_reject_sqlite_urls() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        database_from_url("sqlite:///:memory:")


def test_pytest_settings_uses_an_isolated_sqlite_database() -> None:
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
