from .provider_config import resolve_product_ai


def product_ai_status(organization=None) -> dict[str, object]:
    runtime = resolve_product_ai(organization)
    return {
        "mode": runtime.mode,
        "provider_label": runtime.provider_label,
        "model": runtime.model,
        "configured": runtime.configured,
        "real_requests_enabled": runtime.real_requests_enabled,
    }
