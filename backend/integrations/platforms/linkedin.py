import re

from .base import (
    OfficialPublishRequest,
    OfficialPublishResult,
    provider_failure,
    timeout_failure,
)


class LinkedInConnector:
    POSTS_URL = "https://api.linkedin.com/rest/posts"

    def __init__(self, *, transport, token_store, api_version: str):
        if not re.fullmatch(r"\d{6}", api_version):
            raise ValueError("LinkedIn API version must use YYYYMM format.")
        self.transport = transport
        self.token_store = token_store
        self.api_version = api_version

    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult:
        commentary = request.payload.get("commentary") or request.payload.get("message")
        if not isinstance(commentary, str) or not commentary.strip():
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="LinkedIn 内容缺少正文。",
            )
        token = self.token_store.resolve(request.credential_reference).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
            "X-RestLi-Idempotency-Key": request.idempotency_key,
        }
        payload = {
            "author": f"urn:li:organization:{request.account_external_id}",
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        try:
            response = self.transport.request(
                "POST", self.POSTS_URL, headers=headers, json=payload, timeout_seconds=20,
            )
        except TimeoutError:
            return timeout_failure()
        if not 200 <= response.status_code < 300:
            return provider_failure(
                response.status_code, retry_after=response.headers.get("Retry-After"),
            )
        external_id = str(response.headers.get("x-restli-id", ""))
        return OfficialPublishResult(
            status="SUCCEEDED",
            external_id=external_id,
            external_url=f"https://www.linkedin.com/feed/update/{external_id}" if external_id else "",
        )
