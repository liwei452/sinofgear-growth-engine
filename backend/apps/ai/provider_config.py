import os
from dataclasses import dataclass

from django.conf import settings

from integrations.ai.providers import DeepSeekAIProvider, FakeAIProvider
from integrations.secrets import decrypt_secret

from .models import OrganizationAIProviderConfig


DEEPSEEK_MODELS = ("deepseek-chat", "deepseek-reasoner")
PRICE_TABLE_VERSION = "deepseek-usd-2026-08-18"
DEEPSEEK_USD_PER_MILLION = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}


@dataclass(frozen=True)
class ProductAIRuntime:
    mode: str
    provider_label: str
    provider_code: str
    model: str
    configured: bool
    real_requests_enabled: bool
    provider: object


def resolve_product_ai(organization=None) -> ProductAIRuntime:
    config = None
    if organization is not None:
        config = OrganizationAIProviderConfig.objects.filter(
            organization=organization
        ).first()
    if config is not None:
        if config.enabled and config.encrypted_api_key:
            try:
                api_key = decrypt_secret(config.encrypted_api_key)
            except ValueError:
                api_key = ""
            if api_key:
                return ProductAIRuntime(
                    mode="CONFIGURED_AI",
                    provider_label="DeepSeek 官方 API",
                    provider_code="deepseek",
                    model=config.model,
                    configured=True,
                    real_requests_enabled=True,
                    provider=DeepSeekAIProvider(api_key=api_key, model=config.model),
                )
        return ProductAIRuntime(
            mode="CONFIGURATION_REQUIRED",
            provider_label="真实模型已停用" if config.encrypted_api_key else "真实 AI 尚未配置",
            provider_code="deepseek",
            model=config.model,
            configured=bool(config.encrypted_api_key),
            real_requests_enabled=False,
            provider=FakeAIProvider(),
        )

    provider_code = settings.PRODUCT_AI_PROVIDER
    model = settings.PRODUCT_AI_MODEL
    if provider_code == "fake":
        return ProductAIRuntime(
            mode="FAKE_OFFLINE",
            provider_label="Fake / 离线演示",
            provider_code="fake",
            model=model,
            configured=False,
            real_requests_enabled=False,
            provider=FakeAIProvider(),
        )
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if provider_code == "deepseek" and api_key:
        return ProductAIRuntime(
            mode="CONFIGURED_AI",
            provider_label="DeepSeek 官方 API",
            provider_code="deepseek",
            model=model,
            configured=True,
            real_requests_enabled=True,
            provider=DeepSeekAIProvider(api_key=api_key, model=model),
        )
    return ProductAIRuntime(
        mode="CONFIGURATION_REQUIRED",
        provider_label="真实 AI 尚未配置",
        provider_code="deepseek",
        model=model,
        configured=False,
        real_requests_enabled=False,
        provider=FakeAIProvider(),
    )


def provider_config_payload(config: OrganizationAIProviderConfig | None) -> dict[str, object]:
    return {
        "provider": config.provider if config else "deepseek",
        "model": config.model if config else "deepseek-chat",
        "configured": bool(config and config.encrypted_api_key),
        "enabled": bool(config and config.enabled),
        "daily_budget_micros": config.daily_budget_micros if config else None,
        "daily_spent_micros": config.daily_spent_micros if config else 0,
        "daily_reserved_micros": config.daily_reserved_micros if config else 0,
        "price_table_version": PRICE_TABLE_VERSION,
        "last_tested_at": config.last_tested_at if config else None,
        "last_success_at": config.last_success_at if config else None,
        "last_error_code": config.last_error_code if config else "",
    }
