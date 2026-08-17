from types import SimpleNamespace

from apps.publishing import pre_publish
from apps.publishing.pre_publish import prepare_pre_publish_short_link


def test_prepare_pre_publish_short_link(monkeypatch):
    captured = {}

    def fake_tracking(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="track-1")

    def fake_short(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(code="s_abc123")

    monkeypatch.setattr(pre_publish, "create_tracking_link", fake_tracking)
    monkeypatch.setattr(pre_publish, "create_short_link", fake_short)

    platform_content = SimpleNamespace(
        id="pc-1",
        organization=SimpleNamespace(id="org-1"),
        payload={"landing_page_url": "https://sinfogear.com/gears"},
        platform=SimpleNamespace(code="LINKEDIN"),
        master_content=SimpleNamespace(
            id="master-1",
            brief=SimpleNamespace(
                landing_page_url="https://sinfogear.com/gears",
                campaign=SimpleNamespace(id="campaign-1"),
                product_links=SimpleNamespace(
                    first=lambda: SimpleNamespace(product=SimpleNamespace(id="product-1"))
                ),
            ),
        ),
    )

    result = prepare_pre_publish_short_link(platform_content=platform_content, actor=None)

    assert result.code == "s_abc123"
    assert captured["published_post"] is None
    assert captured["platform"].code == "LINKEDIN"
    assert captured["product"].id == "product-1"


def test_resolve_media_url(monkeypatch):
    fake_storage = SimpleNamespace(
        presigned_download_url=lambda key, expires: f"https://media/{key}"
    )
    monkeypatch.setattr(pre_publish, "get_object_storage", lambda: fake_storage)

    links = [
        SimpleNamespace(asset=SimpleNamespace(mime_type="video/mp4", storage_key="video-1")),
        SimpleNamespace(asset=SimpleNamespace(mime_type="image/png", storage_key="image-1")),
    ]
    platform_content = SimpleNamespace(
        platform=SimpleNamespace(code="TIKTOK"),
        master_content=SimpleNamespace(
            brief=SimpleNamespace(
                asset_links=SimpleNamespace(select_related=lambda name: links)
            )
        ),
    )

    assert pre_publish.resolve_media_url(platform_content) == "https://media/video-1"
    assert pre_publish.resolve_media_url(
        SimpleNamespace(
            platform=SimpleNamespace(code="LINKEDIN"),
            master_content=platform_content.master_content,
        )
    ) is None


def test_resolve_media_keeps_image_vs_video_kind(monkeypatch):
    fake_storage = SimpleNamespace(
        presigned_download_url=lambda key, expires: f"https://media/{key}"
    )
    monkeypatch.setattr(pre_publish, "get_object_storage", lambda: fake_storage)

    links = [
        SimpleNamespace(asset=SimpleNamespace(mime_type="image/png", storage_key="image-1")),
        SimpleNamespace(asset=SimpleNamespace(mime_type="video/mp4", storage_key="video-1")),
    ]

    media = pre_publish.resolve_media(
        SimpleNamespace(
            platform=SimpleNamespace(code="INSTAGRAM"),
            master_content=SimpleNamespace(
                brief=SimpleNamespace(asset_links=SimpleNamespace(select_related=lambda name: links))
            ),
        )
    )

    assert media.url == "https://media/image-1"
    assert media.kind == "IMAGE"
