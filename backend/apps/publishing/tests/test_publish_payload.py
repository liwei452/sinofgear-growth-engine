import pytest
from types import SimpleNamespace

from apps.content.models import PlatformContent
from apps.publishing import pre_publish
from apps.publishing import services as publishing_services
from apps.publishing.publish_payload import PublishPayloadError, build_publish_payload


def test_linkedin_payload_uses_commentary():
    assert build_publish_payload(
        platform_code="LINKEDIN",
        content_payload={"body": "Hello engineering team"},
    ) == {"commentary": "Hello engineering team"}


def test_facebook_payload_uses_message_and_link():
    assert build_publish_payload(
        platform_code="FACEBOOK",
        content_payload={"body": "Capability summary", "landing_page_url": "https://x.example"},
    ) == {"message": "Capability summary", "link": "https://x.example"}


def test_instagram_requires_media_url():
    with pytest.raises(PublishPayloadError):
        build_publish_payload(platform_code="INSTAGRAM", content_payload={"body": "Caption"})
    assert build_publish_payload(
        platform_code="INSTAGRAM",
        content_payload={"body": "Caption"},
        media_url="https://media.example/image.mp4",
    ) == {
        "media_url": "https://media.example/image.mp4",
        "caption": "Caption",
        "media_type": "REELS",
    }


def test_tiktok_and_youtube_require_video_url():
    with pytest.raises(PublishPayloadError):
        build_publish_payload(platform_code="TIKTOK", content_payload={"title": "T"})
    assert build_publish_payload(
        platform_code="TIKTOK",
        content_payload={"title": "T"},
        media_url="https://media.example/video.mp4",
    ) == {"video_url": "https://media.example/video.mp4", "title": "T"}
    assert build_publish_payload(
        platform_code="YOUTUBE",
        content_payload={"title": "T", "body": "Desc"},
        media_url="https://media.example/video.mp4",
    ) == {
        "title": "T",
        "description": "Desc",
        "video_url": "https://media.example/video.mp4",
    }


def test_unknown_platform_raises():
    with pytest.raises(PublishPayloadError):
        build_publish_payload(platform_code="UNKNOWN", content_payload={"body": "x"})


def test_tracking_url_is_embedded_in_text_payload():
    assert build_publish_payload(
        platform_code="LINKEDIN",
        content_payload={"body": "Hello team"},
        tracking_url="https://sinfogear.com/s/s_abc",
    ) == {"commentary": "Hello team\n\nhttps://sinfogear.com/s/s_abc"}
    assert build_publish_payload(
        platform_code="YOUTUBE",
        content_payload={"title": "T", "body": "Desc"},
        media_url="https://media.example/video.mp4",
        tracking_url="https://sinfogear.com/s/s_abc",
    ) == {
        "title": "T",
        "description": "Desc\n\nhttps://sinfogear.com/s/s_abc",
        "video_url": "https://media.example/video.mp4",
    }


def test_publish_official_uses_converted_payload(monkeypatch):
    captured = {}

    def fake_publish(request):
        captured["payload"] = request.payload
        captured["account_external_id"] = request.account_external_id
        return SimpleNamespace(
            status="SUCCEEDED",
            external_id="post-1",
            external_url="",
            error_code="",
            error_message="",
            retryable=False,
            retry_after_seconds=None,
            succeeded=True,
        )

    fake_connector = SimpleNamespace(publish=fake_publish)
    fake_registry = SimpleNamespace(resolve=lambda account: fake_connector)
    fake_runtime = SimpleNamespace(connector_registry=fake_registry)
    monkeypatch.setattr(publishing_services, "get_social_provider_runtime", lambda: fake_runtime)

    fake_task = SimpleNamespace(
        id="t1",
        platform=SimpleNamespace(code="LINKEDIN"),
        platform_content=SimpleNamespace(payload={"body": "Hello team"}),
        social_account=SimpleNamespace(
            external_id="ext-1",
            credential=SimpleNamespace(secret_reference="secret-ref"),
        ),
    )
    result = publishing_services._publish_official(fake_task, 1)

    assert result.status == "SUCCEEDED"
    assert captured["payload"] == {"commentary": "Hello team"}
    assert captured["account_external_id"] == "ext-1"


def test_e2e_approved_content_to_official_connector(publishing_context, monkeypatch):
    content = publishing_context["content"]
    assert content.status == PlatformContent.Status.APPROVED

    captured = {}

    def fake_publish(request):
        captured["payload"] = request.payload
        return SimpleNamespace(
            status="SUCCEEDED",
            external_id="post-1",
            external_url="",
            error_code="",
            error_message="",
            retryable=False,
            retry_after_seconds=None,
            succeeded=True,
        )

    fake_connector = SimpleNamespace(publish=fake_publish)
    fake_runtime = SimpleNamespace(
        connector_registry=SimpleNamespace(resolve=lambda account: fake_connector)
    )
    monkeypatch.setattr(publishing_services, "get_social_provider_runtime", lambda: fake_runtime)
    monkeypatch.setattr(
        pre_publish,
        "prepare_pre_publish_short_link",
        lambda **kwargs: SimpleNamespace(code="s_abc"),
    )
    monkeypatch.setattr(
        pre_publish,
        "build_short_link_url",
        lambda short: "https://sinfogear.com/s/s_abc",
    )

    task = SimpleNamespace(
        id="t1",
        platform=SimpleNamespace(code="LINKEDIN"),
        platform_content=content,
        social_account=publishing_context["account"],
        created_by=publishing_context["actor"],
    )
    result = publishing_services._publish_official(task, 1)

    assert result.status == "SUCCEEDED"
    assert captured["payload"] == {
        "commentary": "Body\n\nhttps://sinfogear.com/s/s_abc",
    }
