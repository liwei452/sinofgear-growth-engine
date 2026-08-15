import os

from django.conf import settings


def product_ai_status() -> dict[str, object]:
    provider = settings.PRODUCT_AI_PROVIDER
    model = settings.PRODUCT_AI_MODEL
    if provider == "fake":
        return {
            "mode": "FAKE_OFFLINE",
            "provider_label": "Fake / 离线演示",
            "model": model,
            "configured": False,
            "real_requests_enabled": False,
        }
    if provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return {
            "mode": "CONFIGURED_AI",
            "provider_label": "DeepSeek 官方 API",
            "model": model,
            "configured": True,
            "real_requests_enabled": True,
        }
    return {
        "mode": "CONFIGURATION_REQUIRED",
        "provider_label": "真实 AI 尚未配置",
        "model": model,
        "configured": False,
        "real_requests_enabled": False,
    }
