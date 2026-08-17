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
