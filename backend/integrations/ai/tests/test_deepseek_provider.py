import json

import pytest

from integrations.ai.providers import DeepSeekAIProvider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.payload


def test_deepseek_provider_uses_bounded_official_json_request(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-never-log")
    monkeypatch.setenv("PRODUCT_AI_MODEL", "deepseek-chat")
    captured = {}

    def opener(request, *, timeout):
        captured.update(request=request, timeout=timeout)
        content = json.dumps({"title": "Verified title", "body": "Verified body"})
        return _Response(json.dumps({
            "choices": [{"message": {"content": content}}],
        }).encode())

    result = DeepSeekAIProvider(opener=opener, timeout_seconds=12).generate(
        prompt="Verified source facts only",
        schema={"type": "object", "required": ["title", "body"]},
    )

    assert result == {"title": "Verified title", "body": "Verified body"}
    assert captured["timeout"] == 12
    assert captured["request"].full_url == "https://api.deepseek.com/chat/completions"
    assert captured["request"].get_header("Authorization") == "Bearer test-secret-never-log"
    payload = json.loads(captured["request"].data)
    assert payload["model"] == "deepseek-chat"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
    assert "test-secret-never-log" not in captured["request"].data.decode()


def test_deepseek_provider_records_usage_metadata(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    content = json.dumps({"title": "T", "body": "B"})

    def opener(_request, *, timeout):
        return _Response(json.dumps({
            "id": "chatcmpl-123",
            "model": "deepseek-chat",
            "choices": [{
                "message": {"content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        }).encode())

    provider = DeepSeekAIProvider(opener=opener, timeout_seconds=12)
    provider.generate(prompt="input", schema={"type": "object", "required": ["title", "body"]})

    assert provider.last_usage["model"] == "deepseek-chat"
    assert provider.last_usage["request_id"] == "chatcmpl-123"
    assert provider.last_usage["finish_reason"] == "stop"
    assert provider.last_usage["prompt_tokens"] == 12
    assert provider.last_usage["completion_tokens"] == 5
    assert provider.last_usage["total_tokens"] == 17
    assert provider.last_usage["latency_seconds"] >= 0


def test_deepseek_provider_never_calls_network_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("network must not be called")

    with pytest.raises(RuntimeError, match="not configured"):
        DeepSeekAIProvider(opener=forbidden).generate(
            prompt="input", schema={"type": "object"},
        )


def test_deepseek_provider_retries_timeout_twice_and_redacts_secret(monkeypatch):
    secret = "secret-that-must-never-appear"
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    attempts = []

    def timeout(_request, *, timeout):
        attempts.append(timeout)
        raise TimeoutError(f"upstream timeout for {secret}")

    with pytest.raises(RuntimeError, match="request failed") as error:
        DeepSeekAIProvider(opener=timeout, sleeper=lambda _seconds: None).generate(
            prompt="input", schema={"type": "object"},
        )

    assert attempts == [30, 30]
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "invalid JSON"),
        (
            json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode(),
            "required schema",
        ),
    ],
)
def test_deepseek_provider_rejects_non_json_and_schema_mismatch(monkeypatch, payload, message):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    provider = DeepSeekAIProvider(opener=lambda *_args, **_kwargs: _Response(payload))

    with pytest.raises(RuntimeError, match=message):
        provider.generate(
            prompt="input",
            schema={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}},
        )


def test_deepseek_provider_rejects_oversized_response_before_parsing(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    provider = DeepSeekAIProvider(
        opener=lambda *_args, **_kwargs: _Response(b"x" * 1_000_001),
    )

    with pytest.raises(RuntimeError, match="size limit"):
        provider.generate(prompt="input", schema={"type": "object"})
