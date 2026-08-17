from .base import (
    OfficialPublishRequest,
    OfficialPublishResult,
    provider_failure,
    timeout_failure,
)


class MetaConnector:
    def __init__(
        self,
        *,
        transport,
        token_store,
        graph_base_url="https://graph.facebook.com/v23.0",
        container_poll_attempts=6,
        container_poll_interval_seconds=5,
    ):
        self.transport = transport
        self.token_store = token_store
        self.graph_base_url = graph_base_url.rstrip("/")
        self.container_poll_attempts = container_poll_attempts
        self.container_poll_interval_seconds = container_poll_interval_seconds

    def _request(self, method: str, path: str, *, token: str, payload: dict | None):
        return self.transport.request(
            method,
            f"{self.graph_base_url}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout_seconds=20,
        )

    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult:
        token = self.token_store.resolve(request.credential_reference).access_token
        try:
            if request.channel == "FACEBOOK":
                return self._publish_facebook(request, token)
            if request.channel == "INSTAGRAM":
                return self._publish_instagram(request, token)
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="该 Meta 渠道不受支持。",
            )
        except TimeoutError:
            return timeout_failure()

    def _publish_facebook(self, request: OfficialPublishRequest, token: str) -> OfficialPublishResult:
        message = request.payload.get("message") or request.payload.get("commentary")
        if not isinstance(message, str) or not message.strip():
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="Facebook 内容缺少正文。",
            )
        payload = {"message": message}
        link = request.payload.get("link")
        if isinstance(link, str) and link:
            payload["link"] = link
        response = self._request(
            "POST", f"{request.account_external_id}/feed", token=token, payload=payload,
        )
        if not 200 <= response.status_code < 300:
            return provider_failure(
                response.status_code, retry_after=response.headers.get("Retry-After"),
            )
        external_id = str(response.json_body.get("id", ""))
        return OfficialPublishResult(
            status="SUCCEEDED",
            external_id=external_id,
            external_url=f"https://www.facebook.com/{external_id}" if external_id else "",
        )

    def _publish_instagram(self, request: OfficialPublishRequest, token: str) -> OfficialPublishResult:
        media_type = str(request.payload.get("media_type", "REELS")).upper()
        if media_type == "IMAGE":
            media_url = request.payload.get("image_url")
        else:
            media_url = request.payload.get("video_url")
        if not isinstance(media_url, str) or not media_url.startswith("https://"):
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="Instagram 内容需要可公开读取的 HTTPS 媒体地址。",
            )
        if media_type == "IMAGE":
            container_payload = {
                "caption": str(request.payload.get("caption", "")),
                "image_url": media_url,
            }
        else:
            container_payload = {
                "caption": str(request.payload.get("caption", "")),
                "video_url": media_url,
                "media_type": "REELS",
            }
        created = self._request(
            "POST", f"{request.account_external_id}/media",
            token=token, payload=container_payload,
        )
        if not 200 <= created.status_code < 300:
            return provider_failure(
                created.status_code, retry_after=created.headers.get("Retry-After"),
            )
        container_id = str(created.json_body.get("id", ""))
        status_code = self._poll_instagram_container(container_id, token=token)
        if status_code is None:
            return OfficialPublishResult(
                status="FAILED", error_code="PROVIDER_UNAVAILABLE",
                error_message="Instagram 媒体仍在处理中，请稍后重试。", retryable=True,
            )
        if status_code == "ERROR":
            return OfficialPublishResult(
                status="FAILED", error_code="VALIDATION_REJECTED",
                error_message="Instagram 媒体容器处理失败。",
            )
        published = self._request(
            "POST", f"{request.account_external_id}/media_publish",
            token=token, payload={"creation_id": container_id},
        )
        if not 200 <= published.status_code < 300:
            return provider_failure(
                published.status_code, retry_after=published.headers.get("Retry-After"),
            )
        return OfficialPublishResult(
            status="SUCCEEDED", external_id=str(published.json_body.get("id", "")),
        )

    def _poll_instagram_container(self, container_id: str, *, token: str) -> str | None:
        import time

        for _ in range(self.container_poll_attempts):
            checked = self._request("GET", container_id, token=token, payload=None)
            if not 200 <= checked.status_code < 300:
                return None
            status = str(checked.json_body.get("status_code", ""))
            if status == "FINISHED":
                return "FINISHED"
            if status == "ERROR":
                return "ERROR"
            if status not in {"IN_PROGRESS", "EXPIRED", ""}:
                return None
            time.sleep(self.container_poll_interval_seconds)
        return None
