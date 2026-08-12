from __future__ import annotations

import json

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _assert_guarded() -> None:
    if not bool(getattr(settings, "DEEPSEEK_E2E_FAKE_ALLOWED", False)):
        raise ImproperlyConfigured("DeepSeek E2E transport is disabled.")
    ownership = str(getattr(settings, "PHASE_A_E2E_OWNERSHIP_SECRET", ""))
    gate = str(getattr(settings, "DEEPSEEK_E2E_GATE", ""))
    run_id = str(getattr(settings, "PHASE_A_E2E_RUN_ID", ""))
    if not run_id or len(ownership) != 64 or gate != ownership:
        raise ImproperlyConfigured("DeepSeek E2E transport ownership is invalid.")


def guarded_e2e_transport() -> httpx.MockTransport:
    """Return a deterministic no-network DeepSeek transport for an owned E2E run."""
    _assert_guarded()

    def respond(request: httpx.Request) -> httpx.Response:
        _assert_guarded()
        authorization = request.headers.get("Authorization", "")
        body = json.loads(request.content)
        prompt = str(body.get("messages", [{}, {}])[-1].get("content", ""))
        credential = authorization.removeprefix("Bearer ")
        scenario = credential.removeprefix("sk-").split("-", 1)[0]
        if scenario == "invalid":
            return httpx.Response(401, request=request)
        if scenario == "balance":
            return httpx.Response(402, request=request)
        if scenario == "retry":
            return httpx.Response(429, headers={"Retry-After": "2"}, request=request)
        schema_text = str(body.get("messages", [{}])[0].get("content", ""))
        marker = "JSON Schema: "
        if marker not in schema_text:
            return httpx.Response(500, request=request)
        schema = json.loads(schema_text.split(marker, 1)[1])
        from .providers import SchemaAwareFakeAIProvider

        output = SchemaAwareFakeAIProvider().generate(
            prompt=prompt, schema=schema
        ).output
        payload = {
            "id": "e2e-deepseek-request",
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(output), "reasoning_content": "discard-me",
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4,
                      "prompt_cache_hit_tokens": 0},
        }
        return httpx.Response(200, json=payload, request=request)

    return httpx.MockTransport(respond)
