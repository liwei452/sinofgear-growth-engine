from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from json import JSONDecodeError

import httpx

from .buffer_types import (
    BufferApiError,
    BufferErrorCode,
    BufferRateLimitResult,
    BufferRateLimitWindow,
)
from .transport import HttpResponse


BUFFER_GRAPHQL_ENDPOINT = "https://api.buffer.com"

_ACCOUNT_QUERY = """
query BufferAccount {
  account {
    id
    name
    organizations {
      id
      name
    }
  }
}
""".strip()

_CHANNELS_QUERY = """
query BufferChannels($organizationId: OrganizationId!) {
  channels(input: { organizationId: $organizationId }) {
    id
    organizationId
    service
    serviceId
    name
    displayName
    avatar
    externalLink
    type
    isDisconnected
    isLocked
    isQueuePaused
    allowedActions
    products
    scopes
  }
}
""".strip()

_CREATE_POST_MUTATION = """
mutation BufferCreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess {
      post {
        id
        channelId
        status
        dueAt
        createdAt
      }
    }
    ... on MutationError {
      __typename
      message
    }
  }
}
""".strip()

_POST_QUERY = """
query BufferPost($input: PostInput!) {
  post(input: $input) {
    id
    channelId
    channelService
    status
    dueAt
    sentAt
    externalLink
    createdAt
    updatedAt
  }
}
""".strip()

_POSTS_QUERY = """
query BufferPosts($input: PostsInput!, $first: Int!, $after: String) {
  posts(input: $input, first: $first, after: $after) {
    edges {
      cursor
      node {
        id
        channelId
        channelService
        status
        text
        createdAt
        dueAt
        sentAt
        schedulingType
        shareMode
        assets {
          type
          mimeType
          source
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
""".strip()


@dataclass(frozen=True)
class BufferGraphQLResponse:
    data: dict
    rate_limit: BufferRateLimitResult


class BufferResponseTooLarge(RuntimeError):
    pass


def _validate_request(method: str, url: str) -> None:
    if method != "POST":
        raise ValueError("Buffer transport only allows POST requests.")
    if url != BUFFER_GRAPHQL_ENDPOINT:
        raise ValueError("Buffer transport only allows the pinned Buffer endpoint.")


class BufferHttpTransport:
    """Production transport pinned to strict TLS, no redirects, bounded reads."""

    def __init__(self, *, max_response_bytes: int = 1_000_000, client_factory=None):
        self._max_response_bytes = max_response_bytes
        self._client_factory = client_factory if client_factory is not None else httpx.Client

    def request(
        self,
        method,
        url,
        *,
        headers,
        json: dict | None,
        timeout_seconds,
        data: bytes | None = None,
    ) -> HttpResponse:
        _validate_request(method, url)
        if data is not None:
            raise ValueError("Buffer transport only supports JSON bodies.")
        timeout = min(max(int(timeout_seconds), 1), 20)
        try:
            with self._client_factory(
                follow_redirects=False, verify=True, timeout=timeout
            ) as client:
                with client.stream(method, url, headers=headers, json=json) as response:
                    raw = self._read_bounded(response)
                    status_code = response.status_code
                    response_headers = self._collect_headers(response.headers)
        except httpx.HTTPError as error:
            raise TimeoutError("Buffer request failed.") from error
        return HttpResponse(
            status_code=status_code,
            json_body=self._parse_json(raw),
            headers=response_headers,
        )

    def _read_bounded(self, response) -> bytes:
        chunks = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise BufferResponseTooLarge("Buffer response exceeded the size limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _collect_headers(self, headers) -> dict[str, str]:
        grouped: dict[str, str] = {}
        for key, value in headers.multi_items():
            lowered = key.lower()
            if lowered in grouped:
                grouped[lowered] = f"{grouped[lowered]}, {value}"
            else:
                grouped[lowered] = value
        return grouped

    @staticmethod
    def _parse_json(raw: bytes) -> dict:
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}


def _split_header_entries(value: str) -> list[str]:
    parts = []
    current = []
    in_quotes = False
    for char in value:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char == "," and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


_ENTRY_RE = re.compile(
    r'^\s*(?:"(?P<quoted>[^"]*)"|(?P<bare>[^;\s]+))\s*(?:;(?P<params>.*))?$'
)


def _parse_entry(entry: str) -> tuple[str, dict[str, str]] | None:
    match = _ENTRY_RE.match(entry.strip())
    if not match:
        return None
    name = match.group("quoted") if match.group("quoted") is not None else match.group("bare")
    params: dict[str, str] = {}
    param_text = match.group("params")
    if param_text:
        for pair in param_text.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            key, raw_value = pair.split("=", 1)
            params[key.strip().lower()] = raw_value.strip().strip('"')
    return name, params


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_rate_limits(
    headers: dict[str, str], *, retry_after_seconds: int | None = None
) -> BufferRateLimitResult:
    policies: dict[str, dict[str, int | None]] = {}
    for entry in _split_header_entries(headers.get("ratelimit-policy", "")):
        parsed = _parse_entry(entry)
        if parsed is None:
            continue
        name, params = parsed
        window_seconds = _parse_int(params.get("w"))
        quota = _parse_int(params.get("q"))
        if window_seconds is None and quota is None:
            continue
        policies[name] = {"window_seconds": window_seconds, "quota": quota}

    live: dict[str, dict[str, int | None]] = {}
    for entry in _split_header_entries(headers.get("ratelimit", "")):
        parsed = _parse_entry(entry)
        if parsed is None:
            continue
        name, params = parsed
        remaining = _parse_int(params.get("r"))
        reset_after_seconds = _parse_int(params.get("t"))
        if remaining is None and reset_after_seconds is None:
            continue
        live[name] = {
            "remaining": remaining,
            "reset_after_seconds": reset_after_seconds,
        }

    windows = []
    for name in sorted(set(policies) | set(live)):
        policy = policies.get(name, {})
        live_window = live.get(name, {})
        windows.append(
            BufferRateLimitWindow(
                window_seconds=policy.get("window_seconds"),
                remaining=live_window.get("remaining"),
                reset_after_seconds=live_window.get("reset_after_seconds"),
                quota=policy.get("quota"),
            )
        )
    return BufferRateLimitResult(
        windows=tuple(windows),
        retry_after_seconds=retry_after_seconds,
    )


class BufferGraphQLClient:
    def __init__(
        self,
        transport,
        *,
        timeout_seconds: int = 20,
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def fetch_account(self, token: str) -> BufferGraphQLResponse:
        return self._execute(token, _ACCOUNT_QUERY, {})

    def fetch_channels(self, token: str, organization_id: str) -> BufferGraphQLResponse:
        return self._execute(token, _CHANNELS_QUERY, {"organizationId": organization_id})

    def create_post(self, token: str, post_input: dict) -> BufferGraphQLResponse:
        if not isinstance(post_input, dict):
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return self._execute(
            token,
            _CREATE_POST_MUTATION,
            {"input": post_input},
            mutation=True,
        )

    def fetch_post(self, token: str, post_id: str) -> BufferGraphQLResponse:
        if type(post_id) is not str or not post_id.strip() or len(post_id.strip()) > 255:
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return self._execute(
            token, _POST_QUERY, {"input": {"id": post_id.strip()}}, operation="post"
        )

    def fetch_posts(
        self, token: str, *, organization_id: str, channel_id: str,
        window_start: datetime, window_end: datetime, after: str | None = None,
        first: int = 50,
    ) -> BufferGraphQLResponse:
        organization_id = _bounded_query_id(organization_id)
        channel_id = _bounded_query_id(channel_id)
        if (
            type(first) is not int or not 1 <= first <= 50
            or after is not None
            and (type(after) is not str or not after or len(after) > 512)
        ):
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        start = _query_datetime(window_start)
        end = _query_datetime(window_end)
        if window_end <= window_start:
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        variables = {
            "input": {
                "organizationId": organization_id,
                "filter": {
                    "channelIds": [channel_id],
                    "createdAt": {"start": start, "end": end},
                },
                "sort": [{"field": "createdAt", "direction": "desc"}],
            },
            "first": first,
            "after": after,
        }
        return self._execute(token, _POSTS_QUERY, variables, operation="posts")

    def _execute(
        self, token: str, query: str, variables: dict, *, mutation: bool = False,
        operation: str = "query",
    ) -> BufferGraphQLResponse:
        if not isinstance(token, str) or not token.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            response = self._transport.request(
                "POST",
                BUFFER_GRAPHQL_ENDPOINT,
                headers=headers,
                json={"query": query, "variables": variables},
                timeout_seconds=self._timeout_seconds,
            )
        except TimeoutError:
            raise BufferApiError(
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.PROVIDER_UNAVAILABLE
            ) from None
        except BufferResponseTooLarge:
            if mutation:
                raise BufferApiError(BufferErrorCode.OUTCOME_UNKNOWN) from None
            raise BufferApiError(
                BufferErrorCode.CONTRACT_ERROR, message="Buffer 返回数据过大。"
            ) from None

        status_code = response.status_code
        header_retry_after = _parse_int(response.headers.get("retry-after"))
        rate_limit = parse_rate_limits(
            response.headers, retry_after_seconds=header_retry_after,
        )
        if 300 <= status_code < 400:
            if mutation:
                raise BufferApiError(BufferErrorCode.OUTCOME_UNKNOWN)
            raise BufferApiError(
                BufferErrorCode.CONTRACT_ERROR, message="Buffer 返回了不安全的跳转。"
            )
        if status_code in (401, 403):
            raise BufferApiError(BufferErrorCode.AUTHENTICATION_REQUIRED)
        if status_code == 429:
            retry_after = _parse_int(response.headers.get("retry-after"))
            raise BufferApiError(
                BufferErrorCode.RATE_LIMITED, retry_after_seconds=retry_after
            )
        if status_code >= 500:
            raise BufferApiError(
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.PROVIDER_UNAVAILABLE
            )
        if status_code != 200:
            raise BufferApiError(
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.CONTRACT_ERROR
            )

        body = response.json_body
        if not isinstance(body, dict):
            raise BufferApiError(
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.CONTRACT_ERROR
            )
        data = body.get("data")
        if mutation and _has_valid_create_post_success(data):
            return BufferGraphQLResponse(data=data, rate_limit=rate_limit)
        if operation == "post" and _has_valid_post_data(data):
            return BufferGraphQLResponse(data=data, rate_limit=rate_limit)
        errors = body.get("errors")
        if errors:
            self._raise_graphql_error(
                errors,
                mutation=mutation,
                operation=operation,
                retry_after_seconds=header_retry_after,
            )
        if data is None:
            if mutation:
                raise BufferApiError(BufferErrorCode.OUTCOME_UNKNOWN)
            raise BufferApiError(
                BufferErrorCode.CONTRACT_ERROR, message="Buffer 返回了空数据。"
            )
        if not isinstance(data, dict):
            raise BufferApiError(
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.CONTRACT_ERROR
            )
        return BufferGraphQLResponse(data=data, rate_limit=rate_limit)

    def _raise_graphql_error(
        self,
        errors,
        *,
        mutation: bool = False,
        operation: str = "query",
        retry_after_seconds: int | None = None,
    ) -> None:
        code = None
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                extensions = first.get("extensions")
                if isinstance(extensions, dict):
                    raw_code = extensions.get("code")
                    if isinstance(raw_code, str):
                        code = raw_code.upper()
        mapping = {
            "UNAUTHORIZED": BufferErrorCode.AUTHENTICATION_REQUIRED,
            "FORBIDDEN": BufferErrorCode.AUTHENTICATION_REQUIRED,
            "RATE_LIMIT_EXCEEDED": BufferErrorCode.RATE_LIMITED,
            "NOT_FOUND": (
                BufferErrorCode.CHANNEL_NOT_FOUND
                if mutation else (
                    BufferErrorCode.POST_NOT_FOUND
                    if operation == "post" else BufferErrorCode.ORGANIZATION_NOT_FOUND
                )
            ),
            "UNEXPECTED": (
                BufferErrorCode.OUTCOME_UNKNOWN
                if mutation else BufferErrorCode.PROVIDER_UNAVAILABLE
            ),
        }
        fallback = (
            BufferErrorCode.OUTCOME_UNKNOWN if mutation else BufferErrorCode.CONTRACT_ERROR
        )
        normalized = mapping.get(code, fallback)
        raise BufferApiError(
            normalized,
            retry_after_seconds=(
                retry_after_seconds
                if normalized is BufferErrorCode.RATE_LIMITED else None
            ),
        )


def _has_valid_create_post_success(data) -> bool:
    if not isinstance(data, dict):
        return False
    create_post = data.get("createPost")
    if (
        not isinstance(create_post, dict)
        or create_post.get("__typename") != "PostActionSuccess"
    ):
        return False
    post = create_post.get("post")
    if not isinstance(post, dict):
        return False
    post_id = post.get("id")
    channel_id = post.get("channelId")
    return (
        isinstance(post_id, str)
        and bool(post_id.strip())
        and isinstance(channel_id, str)
        and bool(channel_id.strip())
    )


def _has_valid_post_data(data) -> bool:
    if type(data) is not dict or type(data.get("post")) is not dict:
        return False
    post = data["post"]
    return all(
        type(post.get(field)) is str and bool(post[field].strip())
        for field in ("id", "channelId", "channelService", "status")
    )


def _bounded_query_id(value: object) -> str:
    if type(value) is not str or not (value := value.strip()) or len(value) > 255:
        raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
    return value


def _query_datetime(value: object) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
