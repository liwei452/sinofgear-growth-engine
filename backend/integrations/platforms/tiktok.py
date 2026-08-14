from .base import (
    OfficialPublishRequest,
    OfficialPublishResult,
    provider_failure,
    timeout_failure,
)


class TikTokConnector:
    CREATOR_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
    DIRECT_POST_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"

    def __init__(self, *, transport, token_store, client_audited: bool):
        self.transport = transport
        self.token_store = token_store
        self.client_audited = client_audited

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
            return OfficialPublishResult(
                status="SUCCEEDED" if self.client_audited else "SUCCEEDED_PRIVATE",
                external_id=str(published.json_body.get("data", {}).get("publish_id", "")),
            )
        except TimeoutError:
            return timeout_failure()
