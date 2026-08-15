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
    value.strip() for value in os.environ.get("TRACKING_TRUSTED_PROXY_CIDRS", "").split(",")
    if value.strip()
]
TED_DISCOVERY_TIMEOUT_SECONDS = int(os.environ.get("TED_DISCOVERY_TIMEOUT_SECONDS", "15"))
TED_DISCOVERY_MAX_RESPONSE_BYTES = int(
    os.environ.get("TED_DISCOVERY_MAX_RESPONSE_BYTES", "2000000")
)
CONTRACTS_FINDER_DISCOVERY_TIMEOUT_SECONDS = int(
    os.environ.get("CONTRACTS_FINDER_DISCOVERY_TIMEOUT_SECONDS", "15")
)
CONTRACTS_FINDER_DISCOVERY_MAX_RESPONSE_BYTES = int(
    os.environ.get("CONTRACTS_FINDER_DISCOVERY_MAX_RESPONSE_BYTES", "2000000")
)
GROWTH_DISCOVERY_SOURCE_FACTORY = os.environ.get("GROWTH_DISCOVERY_SOURCE_FACTORY", "")
GROWTH_WEBSITE_TRANSPORT_FACTORY = os.environ.get("GROWTH_WEBSITE_TRANSPORT_FACTORY", "")
PUBLIC_TRADE_PROVIDER_MODE = os.environ.get(
    "PUBLIC_TRADE_PROVIDER_MODE", "DISABLED",
).strip().upper()
if PUBLIC_TRADE_PROVIDER_MODE not in {"DISABLED", "FIXTURE", "OFFICIAL_PUBLIC"}:
    raise ValueError(
        "PUBLIC_TRADE_PROVIDER_MODE must be DISABLED, FIXTURE, or OFFICIAL_PUBLIC."
    )

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
    "apps.ai.apps.AIConfig",
    "apps.content.apps.ContentConfig",
    "apps.publishing.apps.PublishingConfig",
    "apps.tracking.apps.TrackingConfig",
    "apps.growth.apps.GrowthConfig",
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
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "sinofgear-growth",
    }
}
_cache_url = os.environ.get("CACHE_URL", "")
if _cache_url:
    CACHES["default"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _cache_url,
    }

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
CELERY_BEAT_SCHEDULE = {
    "growth-discovery-hourly": {
        "task": "apps.growth.tasks.scan_due_discovery_profiles",
        "schedule": 3600.0,
    },
    "growth-maps-discovery-hourly": {
        "task": "apps.growth.tasks.scan_due_maps_configs",
        "schedule": 3600.0,
    },
}

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
ASSET_MAX_UPLOAD_BYTES = int(os.environ.get("ASSET_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
ASSET_SPOOL_MEMORY_BYTES = int(
    os.environ.get("ASSET_SPOOL_MEMORY_BYTES", str(8 * 1024 * 1024))
)
PLATFORM_CONNECTOR_CAPABILITIES = {}
PRODUCT_AI_PROVIDER = os.environ.get("PRODUCT_AI_PROVIDER", "fake").strip().lower()
if PRODUCT_AI_PROVIDER not in {"fake", "deepseek"}:
    raise ValueError("PRODUCT_AI_PROVIDER must be 'fake' or 'deepseek'.")
PRODUCT_AI_MODEL = os.environ.get(
    "PRODUCT_AI_MODEL",
    "deepseek-chat" if PRODUCT_AI_PROVIDER == "deepseek" else "fake-v1",
).strip()


def _provider_enabled(name: str) -> bool:
    return os.environ.get(f"{name}_OAUTH_ENABLED", "false").lower() == "true"


SOCIAL_PROVIDER_CONFIG = {
    "META": {
        "enabled": _provider_enabled("META"),
        "client_id": os.environ.get("META_CLIENT_ID", ""),
        "client_secret_reference": os.environ.get("META_CLIENT_SECRET_REFERENCE", ""),
        "authorization_url": "https://www.facebook.com/v23.0/dialog/oauth",
        "redirect_uri": os.environ.get("META_OAUTH_REDIRECT_URI", ""),
        "scopes": ("pages_show_list", "pages_manage_posts", "instagram_content_publish"),
        "api_version": os.environ.get("META_API_VERSION", "v23.0"),
        "audited": _provider_enabled("META_AUDITED"),
    },
    "TIKTOK": {
        "enabled": _provider_enabled("TIKTOK"),
        "client_id": os.environ.get("TIKTOK_CLIENT_KEY", ""),
        "client_secret_reference": os.environ.get("TIKTOK_CLIENT_SECRET_REFERENCE", ""),
        "authorization_url": "https://www.tiktok.com/v2/auth/authorize/",
        "redirect_uri": os.environ.get("TIKTOK_OAUTH_REDIRECT_URI", ""),
        "scopes": ("user.info.basic", "video.publish", "video.upload"),
        "api_version": "v2",
        "audited": _provider_enabled("TIKTOK_AUDITED"),
    },
    "LINKEDIN": {
        "enabled": _provider_enabled("LINKEDIN"),
        "client_id": os.environ.get("LINKEDIN_CLIENT_ID", ""),
        "client_secret_reference": os.environ.get("LINKEDIN_CLIENT_SECRET_REFERENCE", ""),
        "authorization_url": "https://www.linkedin.com/oauth/v2/authorization",
        "redirect_uri": os.environ.get("LINKEDIN_OAUTH_REDIRECT_URI", ""),
        "scopes": ("w_organization_social",),
        "api_version": os.environ.get("LINKEDIN_API_VERSION", ""),
        "audited": _provider_enabled("LINKEDIN_AUDITED"),
    },
    "YOUTUBE": {
        "enabled": _provider_enabled("YOUTUBE"),
        "client_id": os.environ.get("YOUTUBE_CLIENT_ID", ""),
        "client_secret_reference": os.environ.get("YOUTUBE_CLIENT_SECRET_REFERENCE", ""),
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "redirect_uri": os.environ.get("YOUTUBE_OAUTH_REDIRECT_URI", ""),
        "scopes": ("https://www.googleapis.com/auth/youtube.upload",),
        "api_version": "v3",
        "audited": _provider_enabled("YOUTUBE_AUDITED"),
    },
}
SOCIAL_OAUTH_ALLOWED_ORIGINS = tuple(
    value.strip()
    for value in os.environ.get("SOCIAL_OAUTH_ALLOWED_ORIGINS", "").split(",")
    if value.strip()
)
SOCIAL_OAUTH_TOKEN_KEY_REFERENCE = os.environ.get(
    "SOCIAL_OAUTH_TOKEN_KEY_REFERENCE", ""
).strip()
SOCIAL_OAUTH_TOKEN_KEY_VERSION = os.environ.get(
    "SOCIAL_OAUTH_TOKEN_KEY_VERSION", "v1"
).strip()
