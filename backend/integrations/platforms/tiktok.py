from .base import (
    OfficialPublishRequest,
    OfficialPublishResult,
    provider_failure,
    timeout_failure,
)


class TikTokConnector:
    CREATOR_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
    DIRECT_POST_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    def __init__(
        self,
        *,
        transport,
        token_store,
        client_audited: bool,
        status_poll_attempts=10,
        status_poll_interval_seconds=6,
    ):
        self.transport = transport
        self.token_store = token_store
        self.client_audited = client_audited
        self.status_poll_attempts = status_poll_attempts
        self.status_poll_interval_seconds = status_poll_interval_seconds

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}

    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult:
        required = {"explicit", "privacy_level", "allow_comment", "allow_duet", "allow_stitch"}
        if set(request.consent) < required or request.consent.get("explicit") is not True:
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="TikTok 发布前需要你确认可见范围和互动设置。",
            )
        token = self.token_store.resolve(request.credential_reference).access_token
        try:
            creator = self.transport.request(
                "POST", self.CREATOR_URL, headers=self._headers(token), json={}, timeout_seconds=20,
            )
            if not 200 <= creator.status_code < 300:
                return provider_failure(
                    creator.status_code, retry_after=creator.headers.get("Retry-After"),
                )
            privacy = request.consent["privacy_level"] if self.client_audited else "SELF_ONLY"
            options = creator.json_body.get("data", {}).get("privacy_level_options", [])
            if privacy not in options:
                return OfficialPublishResult(
                    status="FAILED", error_code="VALIDATION_REJECTED",
                    error_message="TikTok 当前不允许所选可见范围。",
                )
            video_url = request.payload.get("video_url")
            if not isinstance(video_url, str) or not video_url.startswith("https://"):
                return OfficialPublishResult(
                    status="FAILED", error_code="VALIDATION_REJECTED",
                    error_message="TikTok 内容需要可读取的 HTTPS 视频地址。",
                )
            payload = {
                "post_info": {
                    "title": str(request.payload.get("title", "")),
                    "privacy_level": privacy,
                    "disable_comment": not bool(request.consent["allow_comment"]),
                    "disable_duet": not bool(request.consent["allow_duet"]),
                    "disable_stitch": not bool(request.consent["allow_stitch"]),
                },
                "source_info": {"source": "PULL_FROM_URL", "video_url": video_url},
            }
            published = self.transport.request(
                "POST", self.DIRECT_POST_URL,
                headers=self._headers(token), json=payload, timeout_seconds=30,
            )
            if not 200 <= published.status_code < 300:
                return provider_failure(
                    published.status_code, retry_after=published.headers.get("Retry-After"),
                )
            publish_id = str(published.json_body.get("data", {}).get("publish_id", ""))
            if not publish_id:
                return OfficialPublishResult(
                    status="FAILED", error_code="VALIDATION_REJECTED",
                    error_message="TikTok 未返回可追踪的 publish_id。",
                )
            return self._await_publish_status(token, publish_id)
        except TimeoutError:
            return timeout_failure()

    def _await_publish_status(self, token: str, publish_id: str) -> OfficialPublishResult:
        import time

        for _ in range(self.status_poll_attempts):
            status_response = self.transport.request(
                "POST", self.STATUS_URL,
                headers=self._headers(token),
                json={"publish_id": publish_id},
                timeout_seconds=20,
            )
            if not 200 <= status_response.status_code < 300:
                return provider_failure(
                    status_response.status_code,
                    retry_after=status_response.headers.get("Retry-After"),
                )
            status = str(status_response.json_body.get("data", {}).get("status", "")).upper()
            if status == "PUBLISH_COMPLETE":
                return OfficialPublishResult(
                    status="SUCCEEDED" if self.client_audited else "SUCCEEDED_PRIVATE",
                    external_id=publish_id,
                )
            if "FAILED" in status or status in {"EXPIRED", "CANCELED"}:
                return OfficialPublishResult(
                    status="FAILED", error_code="VALIDATION_REJECTED",
                    error_message=f"TikTok 视频发布失败（{status}）。",
                )
            time.sleep(self.status_poll_interval_seconds)
        return OfficialPublishResult(
            status="FAILED", error_code="PROVIDER_UNAVAILABLE",
            error_message="TikTok 视频仍在处理中，请稍后查询结果。", retryable=True,
        )
