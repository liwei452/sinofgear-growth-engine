import os

os.environ.setdefault("DATABASE_URL", os.environ["RLS_TEST_OWNER_DSN"])

from .settings import *  # noqa: F403
from .settings import database_from_url


DATABASES = {
    "default": database_from_url(os.environ["RLS_TEST_OWNER_DSN"]),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["TIME_ZONE"] = "GMT"
if test_database_name := os.environ.get("RLS_TEST_DATABASE_NAME"):
    DATABASES["default"]["TEST"] = {"NAME": test_database_name}
KNOWLEDGE_TEST_FIXTURE_WRITES = True
OBJECT_STORAGE_BACKEND = "memory"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
TIME_ZONE = "GMT"
TRACKING_HASH_SECRET = "rls-test-only-tracking-secret-material"
TRACKING_HASH_VERSION = "rls-test-v1"
TRACKING_TRUSTED_PROXY_CIDRS = []
