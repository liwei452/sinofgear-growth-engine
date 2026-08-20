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

    assert build_publish_payload(
        platform_code="LINKEDIN",
        content_payload={"body": "Hello engineering team"},
        media_url="https://media.example/gear.jpg",
        media_kind="IMAGE",
    ) == {
        "commentary": "Hello engineering team",
        "image_url": "https://media.example/gear.jpg",
    }
    assert build_publish_payload(
        platform_code="LINKEDIN",
        content_payload={"body": "Direct text survives unsupported media"},
        media_url="https://media.example/gear.mp4",
        media_kind="VIDEO",
    ) == {"commentary": "Direct text survives unsupported media"}


def test_facebook_payload_uses_message_and_link():
    assert build_publish_payload(
        platform_code="FACEBOOK",
        content_payload={"body": "Capability summary", "landing_page_url": "https://x.example"},
    ) == {"message": "Capability summary", "link": "https://x.example"}

    assert build_publish_payload(
        platform_code="FACEBOOK",
        content_payload={"body": "Capability summary"},
        media_url="https://media.example/gear.jpg",
        media_kind="IMAGE",
    ) == {
        "message": "Capability summary",
        "image_url": "https://media.example/gear.jpg",
    }
    assert build_publish_payload(
        platform_code="FACEBOOK",
        content_payload={"body": "Direct text survives unsupported media"},
        media_url="https://media.example/gear.mp4",
        media_kind="VIDEO",
    ) == {"message": "Direct text survives unsupported media"}


def test_official_request_repr_hides_credential_reference():
    from integrations.platforms.base import OfficialPublishRequest

    request = OfficialPublishRequest(
        channel="LINKEDIN",
        account_external_id="legacy-id",
        provider_account_id="channel-1",
        credential_reference="vault://secret-reference",
        payload={"commentary": "Hello"},
        idempotency_key="task-1",
        consent={},
    )

    assert "vault://secret-reference" not in repr(request)


def test_instagram_requires_media_url():
    with pytest.raises(PublishPayloadError):
        build_publish_payload(platform_code="INSTAGRAM", content_payload={"body": "Caption"})
    assert build_publish_payload(
        platform_code="INSTAGRAM",
        content_payload={"body": "Caption"},
        media_url="https://media.example/image.mp4",
    ) == {
        "video_url": "https://media.example/image.mp4",
        "caption": "Caption",
        "media_type": "REELS",
    }
    assert build_publish_payload(
        platform_code="INSTAGRAM",
        content_payload={"body": "Caption"},
        media_url="https://media.example/image.png",
        media_kind="IMAGE",
    ) == {
        "image_url": "https://media.example/image.png",
        "caption": "Caption",
        "media_type": "IMAGE",
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
    monkeypatch.setattr(
        publishing_services,
        "_resolve_media",
        lambda _task: SimpleNamespace(
            url="https://media.example/direct-video.mp4", kind="VIDEO"
        ),
    )
    monkeypatch.setattr(
        publishing_services, "_prepare_tracking_url", lambda _task: None
    )

    def fake_publish(request):
        captured["payload"] = request.payload
        captured["account_external_id"] = request.account_external_id
        captured["idempotency_key"] = request.idempotency_key
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
    connector, request = publishing_services._build_official_call(fake_task)
    result = connector.publish(request)

    assert result.status == "SUCCEEDED"
    assert captured["payload"] == {"commentary": "Hello team"}
    assert captured["account_external_id"] == "ext-1"
    assert captured["idempotency_key"] == "t1"


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
    connector, request = publishing_services._build_official_call(task)
    result = connector.publish(request)

    assert result.status == "SUCCEEDED"
    assert captured["payload"] == {
        "commentary": "Body\n\nhttps://sinfogear.com/s/s_abc",
    }
