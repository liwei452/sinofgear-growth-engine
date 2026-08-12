import os

postgres_test_url = os.environ.get("DIRECTOR_TEST_DATABASE_URL", "")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://sinofgear:sinofgear@localhost:5432/sinofgear"
)

from .settings import *  # noqa: E402,F403

if postgres_test_url:
    DATABASES = {"default": database_from_url(postgres_test_url)}  # noqa: F405
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
OBJECT_STORAGE_BACKEND = "memory"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
KNOWLEDGE_TEST_FIXTURE_WRITES = True
TRACKING_HASH_SECRET = "postgres-test-tracking-secret-material-more-than-32-bytes"
TRACKING_HASH_VERSION = "postgres-test-v1"
TRACKING_TRUSTED_PROXY_CIDRS = []
