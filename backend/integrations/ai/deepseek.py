from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import httpx
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for

from integrations.credentials import CredentialStore, CredentialStoreError, credential_target

from .providers import (
    ProviderAuthenticationError,
    ProviderBalanceError,
    ProviderInvalidOutputError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderRequest,
    ProviderResult,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
SUPPORTED_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_PARSE_FAILED = object()


class DeepSeekProvider:
    def __init__(
        self,
        *,
        credential_store: CredentialStore,
        transport: httpx.BaseTransport | None = None,
        endpoint: str = DEEPSEEK_ENDPOINT,
        max_response_bytes: int = 1_000_000,
        max_json_depth: int = 64,
    ) -> None:
        self._credential_store = credential_store
        self._transport = transport
        self._endpoint = endpoint
        self._max_response_bytes = max_response_bytes
        self._max_json_depth = max_json_depth

    def generate(self, *, prompt: str, schema: dict, execution) -> ProviderResult:
        request = self._request_from_execution(
            prompt=prompt, schema=schema, execution=execution
        )
        target = credential_target(execution.organization_id)
        api_key, credential_available = self._read_credential(target)
        if not credential_available:
            raise ProviderUnavailableError("AI provider credential store is unavailable.")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderAuthenticationError("AI provider credential is missing.")

        payload = self._payload(request)
        timeout = httpx.Timeout(request.timeout_seconds)
        started = perf_counter()
        transport_status, status_code, retry_after, raw_body = self._send(
            payload=payload,
            api_key=api_key,
            timeout=timeout,
        )
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        if transport_status == "timeout":
            raise ProviderTimeoutError("AI provider request timed out.")
        if transport_status == "network":
            raise ProviderNetworkError("AI provider network request failed.")
        if transport_status == "oversized":
            raise ProviderInvalidOutputError("AI provider output exceeded the size limit.")
        self._raise_for_status(status_code, retry_after=retry_after)
        body = self._parse_json_bytes(raw_body)
        if body is _PARSE_FAILED:
            raise ProviderInvalidOutputError("AI provider returned invalid JSON.")
        return self._result(
            body,
            request=request,
            duration_ms=duration_ms,
            forbidden_secret=api_key,
        )

    def _read_credential(self, target: str) -> tuple[str | None, bool]:
        try:
            return self._credential_store.read(target), True
        except CredentialStoreError:
            return None, False

    def _send(
        self, *, payload: dict[str, Any], api_key: str, timeout: httpx.Timeout
    ) -> tuple[str, int, str, bytes]:
        try:
            with httpx.Client(transport=self._transport, timeout=timeout) as client:
                with client.stream(
                    "POST",
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    status_code = response.status_code
                    retry_after = response.headers.get("Retry-After", "")
                    if status_code >= 400:
                        return "ok", status_code, retry_after, b""
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self._max_response_bytes:
                            return "oversized", status_code, retry_after, b""
                        chunks.append(chunk)
                    return "ok", status_code, retry_after, b"".join(chunks)
        except httpx.TimeoutException:
            return "timeout", 0, "", b""
        except httpx.TransportError:
            return "network", 0, "", b""

    @staticmethod
    def _parse_json_bytes(raw_body: bytes) -> Any:
        try:
            return json.loads(raw_body)
        except (ValueError, UnicodeError, RecursionError):
            return _PARSE_FAILED

    @staticmethod
    def _parse_json_text(content: str) -> Any:
        try:
            return json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            return _PARSE_FAILED

    @staticmethod
    def _request_from_execution(*, prompt: str, schema: dict, execution) -> ProviderRequest:
        model = str(execution.model)
        thinking_enabled = bool(execution.thinking_enabled)
        if model not in SUPPORTED_MODELS:
            raise ProviderUnavailableError("AI provider model is unavailable.")
        if (model == "deepseek-v4-pro") != thinking_enabled:
            raise ProviderUnavailableError("AI provider routing decision is invalid.")
        max_tokens = int(execution.max_output_tokens)
        timeout_seconds = float(execution.timeout_seconds)
        if max_tokens <= 0 or timeout_seconds <= 0:
            raise ProviderUnavailableError("AI provider execution limits are invalid.")
        return ProviderRequest(
            model=model,
            thinking_enabled=thinking_enabled,
            prompt=prompt,
            schema=schema,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _payload(request: ProviderRequest) -> dict[str, Any]:
        schema_text = json.dumps(request.schema, sort_keys=True, separators=(",", ":"))
        return {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return one JSON object only. The object must conform to this "
                        f"JSON Schema: {schema_text}"
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            "thinking": {
                "type": "enabled" if request.thinking_enabled else "disabled"
            },
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_tokens,
            "stream": False,
        }

    @staticmethod
    def _raise_for_status(status: int, *, retry_after: str) -> None:
        if status in {401, 403}:
            raise ProviderAuthenticationError("AI provider rejected the credential.")
        if status == 402:
            raise ProviderBalanceError("AI provider balance is insufficient.")
        if status == 429:
            seconds = None
            if len(retry_after) <= 10 and retry_after.isascii() and retry_after.isdigit():
                candidate = int(retry_after)
                if candidate <= 86_400:
                    seconds = candidate
            raise ProviderRateLimitError(retry_after_seconds=seconds)
        if status >= 500:
            raise ProviderUnavailableError("AI provider is temporarily unavailable.")
        if status >= 400:
            raise ProviderUnavailableError("AI provider rejected the request.")

    def _result(
        self,
        body: Any,
        *,
        request: ProviderRequest,
        duration_ms: int,
        forbidden_secret: str,
    ) -> ProviderResult:
        if not isinstance(body, dict):
            raise ProviderInvalidOutputError("AI provider response is malformed.")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderInvalidOutputError("AI provider response has no result.")
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason != "stop":
            raise ProviderInvalidOutputError("AI provider output was incomplete.")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderInvalidOutputError("AI provider output was blank.")
        if forbidden_secret in content:
            raise ProviderInvalidOutputError("AI provider output contained secret material.")
        if len(content.encode("utf-8")) > self._max_response_bytes:
            raise ProviderInvalidOutputError("AI provider output exceeded the size limit.")
        output = self._parse_json_text(content)
        if output is _PARSE_FAILED:
            raise ProviderInvalidOutputError("AI provider returned invalid JSON.")
        if not isinstance(output, dict) or self._json_depth(output) > self._max_json_depth:
            raise ProviderInvalidOutputError("AI provider output structure is invalid.")
        validator_class, schema_valid = self._validator_for(request.schema)
        if not schema_valid:
            raise ProviderInvalidOutputError("AI provider output schema is invalid.") from None
        if not self._matches_schema(
            validator_class, schema=request.schema, output=output
        ):
            raise ProviderInvalidOutputError("AI provider output did not match the schema.") from None

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        metadata = {
            "model": request.model,
            "thinking_enabled": request.thinking_enabled,
            "input_tokens": self._safe_count(usage.get("prompt_tokens")),
            "output_tokens": self._safe_count(usage.get("completion_tokens")),
            "cache_hit_tokens": self._safe_count(
                usage.get("prompt_cache_hit_tokens")
            ),
            "finish_reason": "stop",
            "duration_ms": duration_ms,
        }
        provider_request_id = body.get("id")
        if isinstance(provider_request_id, str) and SAFE_REQUEST_ID.fullmatch(
            provider_request_id
        ):
            metadata["request_id"] = provider_request_id
        return ProviderResult(output=output, metadata=metadata)

    @staticmethod
    def _safe_count(value: Any) -> int:
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else 0
        )

    @staticmethod
    def _validator_for(schema: dict) -> tuple[Any, bool]:
        try:
            validator_class = validator_for(schema)
            validator_class.check_schema(schema)
            return validator_class, True
        except Exception:
            return None, False

    @staticmethod
    def _matches_schema(validator_class: Any, *, schema: dict, output: dict) -> bool:
        try:
            validator_class(schema).validate(output)
            return True
        except JSONSchemaValidationError:
            return False

    @staticmethod
    def _json_depth(value: Any) -> int:
        maximum = 0
        stack = [(value, 1)]
        while stack:
            current, depth = stack.pop()
            maximum = max(maximum, depth)
            if isinstance(current, dict):
                stack.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                stack.extend((item, depth + 1) for item in current)
        return maximum
