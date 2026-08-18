import os

os.environ.setdefault("DATABASE_URL", "postgresql://sinofgear:sinofgear@localhost:5432/sinofgear")

from .settings import *  # noqa: F403

SECRET_KEY = "test-only-secret-key-material-with-more-than-32-bytes"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

KNOWLEDGE_TEST_FIXTURE_WRITES = True
OBJECT_STORAGE_BACKEND = "memory"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PUBLISHING_MOCK_ENABLED = True
TRACKING_HASH_SECRET = "test-only-tracking-secret-material-with-more-than-32-bytes"
TRACKING_HASH_VERSION = "test-v1"
TRACKING_TRUSTED_PROXY_CIDRS = []
