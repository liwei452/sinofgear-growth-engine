from __future__ import annotations

import pytest

import httpx

from integrations.platforms.buffer_client import (
    BUFFER_GRAPHQL_ENDPOINT,
    BufferGraphQLClient,
    BufferHttpTransport,
    BufferResponseTooLarge,
    parse_rate_limits,
)
from integrations.platforms.buffer_types import (
    BufferApiError,
    BufferErrorCode,
    BufferRateLimitWindow,
)
from integrations.platforms.transport import HttpResponse


TOKEN = "buffer-secret-token-abc123"


class RecordingTransport:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else HttpResponse(200, {}, {})
        self.error = error
        self.requests = []

    def request(self, method, url, *, headers, json, timeout_seconds, data=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "timeout_seconds": timeout_seconds,
                "data": data,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def _client(transport):
    return BufferGraphQLClient(transport)


def test_request_uses_post_bearer_json_to_buffer_endpoint():
    transport = RecordingTransport(
        HttpResponse(200, {"data": {"account": {"id": "a"}}}, {})
    )
    _client(transport).fetch_account(TOKEN)

    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == BUFFER_GRAPHQL_ENDPOINT
    assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert request["headers"]["Content-Type"] == "application/json"
    assert set(request["json"]) == {"query", "variables"}
    assert request["json"]["variables"] == {}


def test_channels_query_keeps_organization_id_in_variables():
    transport = RecordingTransport(
        HttpResponse(200, {"data": {"channels": []}}, {})
    )
    _client(transport).fetch_channels(TOKEN, "org-123")

    body = transport.requests[0]["json"]
    assert body["variables"] == {"organizationId": "org-123"}
    assert "org-123" not in body["query"]


def test_http_200_with_data_parses_and_returns_rate_limit():
    transport = RecordingTransport(
        HttpResponse(
            200,
            {"data": {"account": {"id": "acct-1", "name": "Acme"}}},
            {
                "ratelimit": '"200-in-15min";r=198;t=897',
                "ratelimit-policy": '"200-in-15min";q=200;w=900;pk=:x:',
            },
        )
    )
    result = _client(transport).fetch_account(TOKEN)

    assert result.data == {"account": {"id": "acct-1", "name": "Acme"}}
    assert result.rate_limit.windows == (
        BufferRateLimitWindow(
            window_seconds=900, remaining=198, reset_after_seconds=897, quota=200
        ),
    )


def test_http_200_with_graphql_errors_is_failure():
    transport = RecordingTransport(
        HttpResponse(
            200,
            {
                "data": None,
                "errors": [
                    {"message": "secret internal detail", "extensions": {"code": "UNEXPECTED"}}
                ],
            },
            {},
        )
    )
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.PROVIDER_UNAVAILABLE
    assert "secret internal detail" not in str(exc_info.value)


@pytest.mark.parametrize("status", [401, 403])
def test_http_401_403_are_authentication_required(status):
    transport = RecordingTransport(HttpResponse(status, {"errors": []}, {}))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.AUTHENTICATION_REQUIRED


def test_http_429_is_rate_limited_with_retry_after():
    transport = RecordingTransport(
        HttpResponse(429, {"errors": []}, {"retry-after": "42"})
    )
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 42


@pytest.mark.parametrize("status", [500, 502, 503])
def test_http_5xx_is_provider_unavailable(status):
    transport = RecordingTransport(HttpResponse(status, {"errors": []}, {}))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.PROVIDER_UNAVAILABLE


def test_transport_timeout_is_provider_unavailable():
    transport = RecordingTransport(error=TimeoutError("timed out"))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirect_status_is_contract_error(status):
    transport = RecordingTransport(HttpResponse(status, {}, {"location": "https://evil.example"}))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.CONTRACT_ERROR


@pytest.mark.parametrize(
    "body",
    [
        {},  # empty / no data
        {"data": None},  # null data
        {"data": []},  # wrong top-level data type
    ],
)
def test_missing_or_wrong_top_level_is_contract_error(body):
    transport = RecordingTransport(HttpResponse(200, body, {}))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.CONTRACT_ERROR


@pytest.mark.parametrize(
    ("graphql_code", "expected"),
    [
        ("UNAUTHORIZED", BufferErrorCode.AUTHENTICATION_REQUIRED),
        ("FORBIDDEN", BufferErrorCode.AUTHENTICATION_REQUIRED),
        ("RATE_LIMIT_EXCEEDED", BufferErrorCode.RATE_LIMITED),
        ("NOT_FOUND", BufferErrorCode.ORGANIZATION_NOT_FOUND),
        ("UNEXPECTED", BufferErrorCode.PROVIDER_UNAVAILABLE),
        ("SOMETHING_NEW", BufferErrorCode.CONTRACT_ERROR),
    ],
)
def test_graphql_error_codes_are_normalized(graphql_code, expected):
    transport = RecordingTransport(
        HttpResponse(
            200,
            {"errors": [{"message": "raw", "extensions": {"code": graphql_code}}]},
            {},
        )
    )
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is expected


def test_token_never_appears_in_repr_exception_or_log(caplog):
    transport = RecordingTransport(
        HttpResponse(
            200,
            {"errors": [{"message": "bad token buffer-secret-token-abc123", "extensions": {"code": "UNEXPECTED"}}]},
            {},
        )
    )
    client = _client(transport)
    with pytest.raises(BufferApiError) as exc_info:
        client.fetch_account(TOKEN)

    assert TOKEN not in repr(client)
    assert TOKEN not in str(exc_info.value)
    assert TOKEN not in repr(exc_info.value)
    assert TOKEN not in caplog.text


def test_response_too_large_is_contract_error():
    transport = RecordingTransport(error=BufferResponseTooLarge("too large"))
    with pytest.raises(BufferApiError) as exc_info:
        _client(transport).fetch_account(TOKEN)
    assert exc_info.value.code is BufferErrorCode.CONTRACT_ERROR


def test_buffer_transport_does_not_follow_redirects():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"Location": "https://evil.example.com"})

    mock = httpx.MockTransport(handler)
    transport = BufferHttpTransport(
        client_factory=lambda **kwargs: httpx.Client(transport=mock, **kwargs)
    )
    response = transport.request(
        "POST",
        "https://api.buffer.com",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"query": "query { account { id } }"},
        timeout_seconds=20,
    )

    assert response.status_code == 302
    assert calls == ["https://api.buffer.com"]


def test_buffer_transport_rejects_oversized_response():
    def handler(request):
        return httpx.Response(200, content=b"x" * 10)

    mock = httpx.MockTransport(handler)
    transport = BufferHttpTransport(
        max_response_bytes=4,
        client_factory=lambda **kwargs: httpx.Client(transport=mock, **kwargs),
    )
    with pytest.raises(BufferResponseTooLarge):
        transport.request(
            "POST",
            "https://api.buffer.com",
            headers={},
            json={},
            timeout_seconds=20,
        )


def test_rate_limit_headers_are_matched_by_window_name():
    result = parse_rate_limits(
        {
            "ratelimit": '"200-in-15min";r=198;t=897, "1000-in-1day";r=998;t=86397',
            "ratelimit-policy": (
                '"200-in-15min";q=200;w=900;pk=:a:, '
                '"1000-in-1day";q=1000;w=86400;pk=:b:'
            ),
        }
    )
    by_window = {window.window_seconds: window for window in result.windows}
    assert by_window[900].remaining == 198
    assert by_window[900].reset_after_seconds == 897
    assert by_window[900].quota == 200
    assert by_window[86400].remaining == 998
    assert by_window[86400].reset_after_seconds == 86397
    assert by_window[86400].quota == 1000


def test_rate_limit_parse_failure_returns_empty_windows():
    result = parse_rate_limits({"ratelimit": "garbage;no;valid;fields"})
    assert result.windows == ()
    assert result.retry_after_seconds is None
