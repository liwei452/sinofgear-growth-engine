import os

from django.core.exceptions import ImproperlyConfigured

from .e2e_paths import validate_e2e_paths


run_root_text = os.environ.get("SINO_PHASE_A_E2E_ROOT", "")
database_text = os.environ.get("SINO_PHASE_A_E2E_DB", "")
storage_text = os.environ.get("SINO_PHASE_A_E2E_STORAGE", "")
ownership_secret = os.environ.get("SINO_PHASE_A_E2E_OWNERSHIP_SECRET", "")
run_id_text = os.environ.get("SINO_PHASE_A_E2E_RUN_ID", "")
if not run_root_text or not database_text or not storage_text:
    raise ImproperlyConfigured("Isolated Phase A E2E paths are required.")
if len(ownership_secret) != 64 or any(character not in "0123456789abcdef" for character in ownership_secret):
    raise ImproperlyConfigured("A fresh 32-byte Phase A E2E ownership secret is required.")

run_root, database_path, storage_root = validate_e2e_paths(
    run_root_text, database_text, storage_text
)
if run_id_text != str(run_root):
    raise ImproperlyConfigured("The Phase A E2E run identity must match its canonical root.")

from .test_settings import *  # noqa: E402,F403

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
PHASE_A_E2E_OWNERSHIP_SECRET = ownership_secret
PHASE_A_E2E_RUN_ID = run_id_text
PLATFORM_CONNECTOR_CAPABILITIES = {
    code: ["PUBLISH"]
    for code in ("FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE")
}
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
E2E_WEB_ORIGIN = os.environ.get("SINO_PHASE_A_E2E_WEB_ORIGIN", "http://127.0.0.1")
CORS_ALLOWED_ORIGINS = [E2E_WEB_ORIGIN]
CSRF_TRUSTED_ORIGINS = [E2E_WEB_ORIGIN]
