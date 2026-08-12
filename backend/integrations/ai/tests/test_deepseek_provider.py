import json
from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
from django.test import override_settings

from integrations.ai.deepseek import DeepSeekProvider
from integrations.ai.providers import (
    ProviderAuthenticationError,
    ProviderBalanceError,
    ProviderInvalidOutputError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderRequest,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderRegistry,
)
from integrations.ai.providers import register_deepseek_provider
from integrations.credentials import CredentialStoreError, CredentialStoreUnavailableError


SECRET = "sk-secret-from-fake-store"
TARGET = "SinofGear/DeepSeek/10000000-0000-4000-8000-000000000001"
SCHEMA = {
    "type": "object",
    "required": ["title"],
    "properties": {"title": {"type": "string"}},
    "additionalProperties": False,
}


class FakeCredentialStore:
    def __init__(self, value=SECRET):
        self.value = value
        self.reads = []

    def read(self, target):
        self.reads.append(target)
        return self.value

    def write(self, target, secret):
        raise AssertionError("provider must not write credentials")

    def delete(self, target):
        raise AssertionError("provider must not delete credentials")


@dataclass(frozen=True)
class Execution:
    organization_id: UUID
    model: str
    thinking_enabled: bool
    max_output_tokens: int = 400
    timeout_seconds: float = 12


def execution(*, model="deepseek-v4-flash", thinking=False):
    return Execution(
        organization_id=UUID("10000000-0000-4000-8000-000000000001"),
        model=model,
        thinking_enabled=thinking,
    )


def response_payload(
    content='{"title":"DIN 6 gear"}',
    *,
    finish_reason="stop",
    reasoning_content=None,
    usage=None,
):
    message = {"content": content}
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return {
        "id": "req_safe-123",
        "model": "deepseek-v4-flash",
        "choices": [{"finish_reason": finish_reason, "message": message}],
        "usage": usage
        or {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "prompt_cache_hit_tokens": 3,
        },
    }


def provider_for(handler, *, store=None, max_response_bytes=1_000_000):
    return DeepSeekProvider(
        credential_store=store or FakeCredentialStore(),
        transport=httpx.MockTransport(handler),
        max_response_bytes=max_response_bytes,
    )


def safe_response(request, payload=None, *, status=200, headers=None):
    return httpx.Response(
        status,
        json=response_payload() if payload is None else payload,
        headers=headers,
        request=request,
    )


def assert_exception_isolated(error, *forbidden):
    """Check the whole attached exception graph, not only rendered messages."""
    assert error.__cause__ is None
    assert error.__context__ is None
    pending = [error]
    seen = set()
    rendered = []
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        rendered.append(repr(value))
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
        elif hasattr(value, "__dict__"):
            pending.extend(vars(value).values())
    snapshot = " ".join(rendered)
    for secret in forbidden:
        assert secret not in snapshot


def test_flash_request_disables_thinking_and_requests_json():
    captured = {}

    def handler(request):
        captured["headers"] = request.headers
        captured["json"] = json.loads(request.content)
        return safe_response(request)

    store = FakeCredentialStore()
    result = provider_for(handler, store=store).generate(
        prompt="Return JSON for this content task.",
        schema=SCHEMA,
        execution=execution(),
    )

    assert captured["json"]["model"] == "deepseek-v4-flash"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["stream"] is False
    assert captured["json"]["max_tokens"] == 400
    assert "Return one JSON object only." in captured["json"]["messages"][0]["content"]
    assert captured["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert store.reads == [TARGET]
    assert result.output == {"title": "DIN 6 gear"}


def test_pro_enables_thinking_and_discards_reasoning_content():
    private = "private chain that must never escape"

    def handler(request):
        payload = response_payload(reasoning_content=private)
        payload["model"] = "deepseek-v4-pro"
        return safe_response(request, payload)

    result = provider_for(handler).generate(
        prompt="complex analysis", schema=SCHEMA, execution=execution(model="deepseek-v4-pro", thinking=True)
    )

    assert result.output == {"title": "DIN 6 gear"}
    assert private not in repr(result)
    assert private not in json.dumps(result.metadata)
    assert result.metadata["thinking_enabled"] is True


def test_request_value_can_be_built_explicitly():
    request = ProviderRequest(
        model="deepseek-v4-flash",
        thinking_enabled=False,
        prompt="prompt",
        schema=SCHEMA,
        max_tokens=100,
        timeout_seconds=5,
    )
    assert request.max_tokens == 100


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, ProviderAuthenticationError),
        (402, ProviderBalanceError),
        (500, ProviderUnavailableError),
        (503, ProviderUnavailableError),
    ],
)
def test_http_failures_are_controlled_and_secret_safe(status, error_type):
    body_secret = "upstream-body-must-not-escape"

    def handler(request):
        return httpx.Response(status, text=body_secret, request=request)

    with pytest.raises(error_type) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())

    rendered = f"{captured.value!s} {captured.value!r}"
    assert SECRET not in rendered
    assert f"Bearer {SECRET}" not in rendered
    assert body_secret not in rendered


def test_rate_limit_exposes_only_numeric_retry_after():
    def handler(request):
        return httpx.Response(
            429,
            text="sensitive upstream response",
            headers={"Retry-After": "17"},
            request=request,
        )

    with pytest.raises(ProviderRateLimitError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())

    assert captured.value.retry_after_seconds == 17
    assert "sensitive" not in repr(captured.value)


@pytest.mark.parametrize(
    ("transport_error", "error_type"),
    [
        (httpx.ReadTimeout("secret timeout detail"), ProviderTimeoutError),
        (httpx.ConnectError("secret network detail"), ProviderNetworkError),
    ],
)
def test_transport_failures_are_controlled(transport_error, error_type):
    def handler(request):
        transport_error.request = request
        raise transport_error

    with pytest.raises(error_type) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, SECRET, f"Bearer {SECRET}", "secret")


def test_stream_failure_is_controlled_without_retaining_authorization():
    class FailingStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"id":"partial"'
            raise httpx.ReadError("stream diagnostic with secret")

    def handler(request):
        return httpx.Response(200, stream=FailingStream(), request=request)

    with pytest.raises(ProviderNetworkError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, SECRET, f"Bearer {SECRET}", "secret")


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        response_payload(finish_reason="length"),
        response_payload(content="   "),
        response_payload(content="not-json private body"),
        response_payload(content="[]"),
        response_payload(content='{"wrong":"shape"}'),
    ],
)
def test_invalid_outputs_raise_a_controlled_body_safe_error(payload):
    def handler(request):
        return safe_response(request, payload)

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    rendered = f"{captured.value!s} {captured.value!r}"
    assert SECRET not in rendered
    assert "private body" not in rendered


def test_oversized_response_is_rejected_without_exposing_body():
    private = "oversized-private-value"

    def handler(request):
        return safe_response(request, response_payload(content=json.dumps({"title": private * 20})))

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler, max_response_bytes=100).generate(
            prompt="p", schema=SCHEMA, execution=execution()
        )
    assert private not in repr(captured.value)


def test_oversized_stream_stops_reading_at_the_cap():
    read_chunks = []

    class CountingStream(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(100):
                read_chunks.append(index)
                yield b"x" * 32

    def handler(request):
        return httpx.Response(200, stream=CountingStream(), request=request)

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler, max_response_bytes=64).generate(
            prompt="p", schema=SCHEMA, execution=execution()
        )
    assert len(read_chunks) == 3
    assert_exception_isolated(captured.value, SECRET, f"Bearer {SECRET}")


def test_invalid_outer_json_does_not_retain_raw_decoder_document():
    private = "private-outer-response"

    def handler(request):
        return httpx.Response(200, content=("{" + private).encode(), request=request)

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, private, SECRET)


def test_invalid_content_json_does_not_retain_raw_decoder_document():
    private = "private-content-response"

    def handler(request):
        return safe_response(request, response_payload(content="{" + private))

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, private, SECRET)


def test_schema_mismatch_does_not_retain_private_output_in_validator_error():
    private = "private-schema-mismatch"

    def handler(request):
        return safe_response(
            request, response_payload(content=json.dumps({"wrong": private}))
        )

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, private, SECRET)


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "bad://private-resolver-target"},
        {"$ref": "#"},
    ],
)
def test_hostile_schema_resolution_is_controlled_and_isolated(schema):
    private = "private-output-for-hostile-schema"

    def handler(request):
        return safe_response(
            request, response_payload(content=json.dumps({"title": private}))
        )

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(
            prompt="p", schema=schema, execution=execution()
        )
    assert_exception_isolated(
        captured.value,
        private,
        SECRET,
        "bad://private-resolver-target",
        "private-resolver-target",
    )


def test_extremely_nested_outer_json_is_a_controlled_error():
    raw = ("[" * 1100 + "]" * 1100).encode()

    def handler(request):
        return httpx.Response(200, content=raw, request=request)

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert_exception_isolated(captured.value, SECRET, f"Bearer {SECRET}")


def test_huge_numeric_retry_after_is_ignored_safely():
    huge = "9" * 5000

    def handler(request):
        return httpx.Response(
            429, headers={"Retry-After": huge}, content=b"private", request=request
        )

    with pytest.raises(ProviderRateLimitError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert captured.value.retry_after_seconds is None
    assert_exception_isolated(captured.value, huge, SECRET, f"Bearer {SECRET}")


def test_excessively_nested_output_is_rejected():
    nested = '"value"'
    for _ in range(70):
        nested = '{"x":' + nested + "}"

    def handler(request):
        return safe_response(request, response_payload(content=nested))

    with pytest.raises(ProviderInvalidOutputError):
        provider_for(handler).generate(prompt="p", schema={"type": "object"}, execution=execution())


def test_metadata_is_allowlisted_and_malicious_request_id_is_dropped():
    malicious = "request-id\r\nAuthorization: Bearer " + SECRET

    def handler(request):
        payload = response_payload(
            usage={
                "prompt_tokens": 21,
                "completion_tokens": 8,
                "prompt_cache_hit_tokens": 5,
                "secret_usage_extension": SECRET,
            }
        )
        payload["id"] = malicious
        payload["secret_extension"] = SECRET
        return safe_response(request, payload, headers={"x-request-id": malicious})

    result = provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())

    assert result.metadata["input_tokens"] == 21
    assert result.metadata["output_tokens"] == 8
    assert result.metadata["cache_hit_tokens"] == 5
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["model"] == "deepseek-v4-flash"
    assert "request_id" not in result.metadata
    assert SECRET not in repr(result)
    assert set(result.metadata) <= {
        "request_id",
        "model",
        "thinking_enabled",
        "input_tokens",
        "output_tokens",
        "cache_hit_tokens",
        "finish_reason",
        "duration_ms",
    }


def test_missing_credential_fails_before_transport():
    def handler(request):
        raise AssertionError("network must not be used without a credential")

    with pytest.raises(ProviderAuthenticationError):
        provider_for(handler, store=FakeCredentialStore(None)).generate(
            prompt="p", schema=SCHEMA, execution=execution()
        )


def test_credential_read_failure_does_not_leak_store_diagnostics():
    class FailingStore(FakeCredentialStore):
        def read(self, target):
            raise CredentialStoreError(f"vault diagnostic {SECRET}")

    with pytest.raises(ProviderUnavailableError) as captured:
        provider_for(lambda request: safe_response(request), store=FailingStore()).generate(
            prompt="p", schema=SCHEMA, execution=execution()
        )
    assert SECRET not in f"{captured.value!s} {captured.value!r}"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_response_content_that_echoes_the_credential_is_rejected():
    def handler(request):
        return safe_response(
            request, response_payload(content=json.dumps({"title": SECRET}))
        )

    with pytest.raises(ProviderInvalidOutputError) as captured:
        provider_for(handler).generate(prompt="p", schema=SCHEMA, execution=execution())
    assert SECRET not in f"{captured.value!s} {captured.value!r}"


def test_registry_does_not_register_deepseek_when_store_is_unsupported(monkeypatch):
    registry = ProviderRegistry()

    def unavailable():
        raise CredentialStoreUnavailableError("unsafe diagnostic")

    monkeypatch.setattr("integrations.credentials.get_credential_store", unavailable)
    assert register_deepseek_provider(registry) is False
    with pytest.raises(ValueError, match="Unknown AI provider 'deepseek'"):
        registry.get("deepseek")


@override_settings(
    DEEPSEEK_API_BASE_URL="https://api.deepseek.com",
    DEEPSEEK_MAX_RESPONSE_BYTES=321,
    DEEPSEEK_MAX_JSON_DEPTH=17,
)
def test_registry_registers_deepseek_with_an_available_store(monkeypatch):
    registry = ProviderRegistry()
    monkeypatch.setattr(
        "integrations.credentials.get_credential_store", lambda: FakeCredentialStore()
    )
    assert register_deepseek_provider(registry) is True
    assert isinstance(registry.get("deepseek"), DeepSeekProvider)
