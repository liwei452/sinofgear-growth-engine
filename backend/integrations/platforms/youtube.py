from urllib.parse import urlsplit

from .base import (
    OfficialPublishRequest,
    OfficialPublishResult,
    provider_failure,
    timeout_failure,
)


class YouTubeConnector:
    INITIALIZE_URL = (
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status"
    )
    MAX_MEDIA_BYTES = 256 * 1024 * 1024

    def __init__(self, *, transport, token_store, media_loader):
        self.transport = transport
        self.token_store = token_store
        self.media_loader = media_loader

    @staticmethod
    def _invalid() -> OfficialPublishResult:
        return OfficialPublishResult(
            status="FAILED",
            error_code="VALIDATION_REJECTED",
            error_message="YouTube 视频资料或发布设置不完整。",
        )

    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult:
        title = request.payload.get("title")
        description = request.payload.get("description", "")
        video_url = request.payload.get("video_url")
        privacy = request.consent.get("privacy_status")
        if (
            request.channel != "YOUTUBE"
            or request.consent.get("explicit") is not True
            or privacy not in {"private", "unlisted", "public"}
            or not isinstance(title, str)
            or not 1 <= len(title.strip()) <= 100
            or not isinstance(description, str)
            or len(description) > 5000
            or not isinstance(video_url, str)
            or not video_url.startswith("https://")
        ):
            return self._invalid()
        try:
            media = self.media_loader.load(video_url, max_bytes=self.MAX_MEDIA_BYTES)
            if not isinstance(media, bytes) or not media or len(media) > self.MAX_MEDIA_BYTES:
                return self._invalid()
            token = self.token_store.resolve(request.credential_reference).access_token
            initialized = self.transport.request(
                "POST",
                self.INITIALIZE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(len(media)),
                    "X-Idempotency-Key": request.idempotency_key,
                },
                json={
                    "snippet": {"title": title.strip(), "description": description},
                    "status": {"privacyStatus": privacy},
                },
                timeout_seconds=30,
            )
            if not 200 <= initialized.status_code < 300:
                return provider_failure(
                    initialized.status_code,
                    retry_after=initialized.headers.get("Retry-After"),
                )
            upload_url = initialized.headers.get("Location", "")
            parsed = urlsplit(upload_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.googleapis.com"
                or not parsed.path.startswith("/upload/youtube/v3/")
                or parsed.username
                or parsed.password
            ):
                return OfficialPublishResult(
                    status="FAILED",
                    error_code="PROVIDER_UNAVAILABLE",
                    error_message="YouTube 上传会话暂时不可用。",
                    retryable=True,
                )
            uploaded = self.transport.request(
                "PUT",
                upload_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(media)),
                },
                json=None,
                data=media,
                timeout_seconds=30,
            )
            if not 200 <= uploaded.status_code < 300:
                return provider_failure(
                    uploaded.status_code,
                    retry_after=uploaded.headers.get("Retry-After"),
                )
            video_id = uploaded.json_body.get("id")
            if not isinstance(video_id, str) or not video_id:
                return OfficialPublishResult(
                    status="FAILED",
                    error_code="PROVIDER_UNAVAILABLE",
                    error_message="YouTube 未返回可核验的视频编号。",
                    retryable=True,
                )
            return OfficialPublishResult(
                status="SUCCEEDED_PRIVATE" if privacy == "private" else "SUCCEEDED",
                external_id=video_id,
                external_url=f"https://www.youtube.com/watch?v={video_id}",
            )
        except TimeoutError:
            return timeout_failure()
