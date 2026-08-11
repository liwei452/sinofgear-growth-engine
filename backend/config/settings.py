import os
from urllib.parse import unquote, urlparse


def database_from_url(database_url: str) -> dict[str, object]:
    """Return Django database settings from a PostgreSQL URL."""
    parsed = urlparse(database_url)

    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
        }
    raise ValueError("DATABASE_URL must use a PostgreSQL URL (postgresql://)")


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-django-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
TRACKING_HASH_SECRET = os.environ.get("TRACKING_HASH_SECRET", "")
TRACKING_HASH_VERSION = os.environ.get("TRACKING_HASH_VERSION", "v1")
TRACKING_TRUSTED_PROXY_CIDRS = [
    value.strip()
    for value in os.environ.get("TRACKING_TRUSTED_PROXY_CIDRS", "").split(",")
    if value.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.common.apps.CommonConfig",
    "apps.identity.apps.IdentityConfig",
    "apps.platforms.apps.PlatformsConfig",
    "apps.audit.apps.AuditConfig",
    "apps.knowledge.apps.KnowledgeConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.assets.apps.AssetsConfig",
    "apps.campaigns.apps.CampaignsConfig",
    "apps.jobs.apps.JobsConfig",
    "apps.sources.apps.SourcesConfig",
    "apps.leads.apps.LeadsConfig",
    "apps.ai.apps.AIConfig",
    "apps.content.apps.ContentConfig",
    "apps.publishing.apps.PublishingConfig",
    "apps.tracking.apps.TrackingConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["apps.common.renderers.RecoverableErrorJSONRenderer"],
}
SPECTACULAR_SETTINGS = {
    "TITLE": "SinofGear Growth Engine API",
    "VERSION": "v1",
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "apps.common.openapi.enforce_mutation_error_contract",
        "apps.publishing.openapi.enforce_publish_attempt_bound",
    ],
    "APPEND_COMPONENTS": {
        "schemas": {
            "ApiError": {
                "type": "object",
                "required": ["code", "message", "recovery_action"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "recovery_action": {"type": "string"},
                    "detail": {"type": "string"},
                    "errors": {"type": "object", "additionalProperties": True},
                },
            }
        }
    },
    "ENUM_NAME_OVERRIDES": {
        "KnowledgeStatusEnum": [
            ("SUGGESTED", "Suggested"),
            ("APPROVED", "Approved"),
            ("REJECTED", "Rejected"),
            ("DEPRECATED", "Deprecated"),
        ],
        "ProductStatusEnum": [
            ("DRAFT", "Draft"),
            ("ACTIVE", "Active"),
            ("ARCHIVED", "Archived"),
        ],
        "ActiveStatusEnum": [("ACTIVE", "Active"), ("INACTIVE", "Inactive")],
        "ProductConceptRoleEnum": [
            ("TYPE", "Type"),
            ("MATERIAL", "Material"),
            ("PROCESS", "Process"),
            ("STANDARD", "Standard"),
            ("APPLICATION", "Application"),
            ("PARAMETER", "Parameter"),
        ],
        "SocialAccountPublishModeEnum": [
            ("API_AUTO", "API automatic"),
            ("API_CONFIRM", "API confirmation"),
            ("EXPORT_PACKAGE", "Export package"),
            ("MANUAL", "Manual"),
        ],
        "PublishTaskStatusEnum": [
            ("SCHEDULED", "Scheduled"),
            ("QUEUED", "Queued"),
            ("RUNNING", "Running"),
            ("SUCCEEDED", "Succeeded"),
            ("FAILED", "Failed"),
            ("CANCELED", "Canceled"),
        ],
    },
}

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

OBJECT_STORAGE_BACKEND = os.environ.get("OBJECT_STORAGE_BACKEND", "minio")
OBJECT_STORAGE_FILESYSTEM_ROOT = os.environ.get("OBJECT_STORAGE_FILESYSTEM_ROOT", "")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_PUBLIC_ENDPOINT = os.environ.get("MINIO_PUBLIC_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "sinofgear-assets")
MINIO_REGION = os.environ.get("MINIO_REGION", "us-east-1")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"
MINIO_PUBLIC_SECURE = os.environ.get("MINIO_PUBLIC_SECURE", "false").lower() == "true"
ASSET_MAX_UPLOAD_BYTES = int(
    os.environ.get("ASSET_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024))
)
ASSET_SPOOL_MEMORY_BYTES = int(
    os.environ.get("ASSET_SPOOL_MEMORY_BYTES", str(8 * 1024 * 1024))
)
PLATFORM_CONNECTOR_CAPABILITIES = {}
PHASE_B1_SCHEMA_FAKE_ALLOWED = (
    os.environ.get("SINO_PHASE_B1_SCHEMA_FAKE_ALLOWED", "false").lower() == "true"
)
