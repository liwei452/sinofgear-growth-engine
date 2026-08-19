"""Shared metadata for disclosing whether an AI path used real generation or fell back."""

from __future__ import annotations


def ai_success_metadata(provider: str, model: str) -> dict:
    return {
        "execution_mode": "AI_GENERATION",
        "provider": provider,
        "model": model,
        "fallback_used": False,
        "fallback_reason": "",
    }


def ai_fallback_metadata(provider: str, model: str, reason: str) -> dict:
    return {
        "execution_mode": "AUTOMATION",
        "provider": provider,
        "model": model,
        "fallback_used": True,
        "fallback_reason": str(reason)[:500],
    }
