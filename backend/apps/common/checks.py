from django.conf import settings
from django.core.checks import Error, register


INSECURE_SECRET_KEYS = {
    "development-only-django-secret-key",
}


@register()
def check_production_secrets(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    errors = []
    if (
        settings.SECRET_KEY in INSECURE_SECRET_KEYS
        or len(settings.SECRET_KEY.encode("utf-8")) < 32
    ):
        errors.append(Error(
            "DJANGO_SECRET_KEY must be a unique, unpredictable value of at least 32 bytes.",
            hint="Set DJANGO_SECRET_KEY to a dedicated value before running outside development.",
            id="common.E001",
        ))
    return errors
