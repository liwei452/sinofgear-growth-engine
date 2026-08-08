import os

os.environ.setdefault("DATABASE_URL", "postgresql://sinofgear:sinofgear@localhost:5432/sinofgear")

from .settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

KNOWLEDGE_TEST_FIXTURE_WRITES = True
