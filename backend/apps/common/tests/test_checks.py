from django.test import override_settings

from apps.common.checks import check_production_secrets


@override_settings(DEBUG=False, SECRET_KEY="development-only-django-secret-key")
def test_production_insecure_secret_is_rejected():
    errors = check_production_secrets(None)
    assert any(error.id == "common.E001" for error in errors)


@override_settings(DEBUG=False, SECRET_KEY="x" * 40)
def test_production_strong_secret_passes():
    assert check_production_secrets(None) == []
