import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .test_settings import *  # noqa: F403


MARKER = "sinofgear-phase-a-e2e-"
run_root_text = os.environ.get("SINO_PHASE_A_E2E_ROOT", "")
database_text = os.environ.get("SINO_PHASE_A_E2E_DB", "")
storage_text = os.environ.get("SINO_PHASE_A_E2E_STORAGE", "")
if not run_root_text or not database_text or not storage_text:
    raise ImproperlyConfigured("Isolated Phase A E2E paths are required.")

run_root = Path(run_root_text).resolve()
database_path = Path(database_text).resolve()
storage_root = Path(storage_text).resolve()
if not run_root.name.startswith(MARKER):
    raise ImproperlyConfigured("Phase A E2E root is missing its safety marker.")
if database_path.parent != run_root or run_root not in storage_root.parents:
    raise ImproperlyConfigured("Phase A E2E database and storage must stay inside the run root.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(database_path),
        "OPTIONS": {"timeout": 20},
    }
}
OBJECT_STORAGE_BACKEND = "filesystem"
OBJECT_STORAGE_FILESYSTEM_ROOT = str(storage_root)
PHASE_A_E2E_SEED_ALLOWED = True
PLATFORM_CONNECTOR_CAPABILITIES = {
    code: ["PUBLISH"]
    for code in ("FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE")
}
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
E2E_WEB_ORIGIN = os.environ.get("SINO_PHASE_A_E2E_WEB_ORIGIN", "http://127.0.0.1")
CORS_ALLOWED_ORIGINS = [E2E_WEB_ORIGIN]
CSRF_TRUSTED_ORIGINS = [E2E_WEB_ORIGIN]
