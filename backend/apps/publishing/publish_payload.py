"""Single conversion layer from platform content to connector publish payload."""

from __future__ import annotations


class PublishPayloadError(ValueError):
    pass


def build_publish_payload(
    *,
    platform_code: str,
    content_payload: dict,
    media_url: str | None = None,
    tracking_url: str | None = None,
) -> dict:
    code = (platform_code or "").strip().upper()
    body = str(content_payload.get("body") or "").strip()
    title = str(content_payload.get("title") or "").strip()
    landing_page_url = str(content_payload.get("landing_page_url") or "").strip()

    def _with_tracking(text: str) -> str:
        if not tracking_url:
            return text
        return f"{text}\n\n{tracking_url}" if text else tracking_url

    if code == "LINKEDIN":
        if not body:
            raise PublishPayloadError("LinkedIn content is missing body text.")
        return {"commentary": _with_tracking(body)}

    if code == "FACEBOOK":
        if not body:
            raise PublishPayloadError("Facebook content is missing body text.")
        payload = {"message": _with_tracking(body)}
        if landing_page_url:
            payload["link"] = landing_page_url
        return payload

    if code == "INSTAGRAM":
        if not media_url or not media_url.startswith("https://"):
            raise PublishPayloadError("Instagram content needs a public HTTPS media URL.")
        return {"media_url": media_url, "caption": _with_tracking(body), "media_type": "REELS"}

    if code == "TIKTOK":
        if not media_url or not media_url.startswith("https://"):
            raise PublishPayloadError("TikTok content needs a public HTTPS video URL.")
        return {"video_url": media_url, "title": title}

    if code == "YOUTUBE":
        if not media_url or not media_url.startswith("https://"):
            raise PublishPayloadError("YouTube content needs a public HTTPS video URL.")
        return {"title": title, "description": _with_tracking(body), "video_url": media_url}

    raise PublishPayloadError(f"Unsupported platform code {code!r}.")
