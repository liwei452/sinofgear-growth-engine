from types import SimpleNamespace

from apps.growth import publishing as growth_publishing
from apps.growth.publishing import delegate_channel_package_to_publish_task


def test_delegate_package_creates_publish_task(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="pt-1", status="QUEUED")

    monkeypatch.setattr(growth_publishing, "create_publish_task", fake_create)
    package = SimpleNamespace(
        status="APPROVED",
        id="pkg-1",
        source_platform_content=SimpleNamespace(id="content-1"),
    )
    account = SimpleNamespace(id="acc-1")

    result = delegate_channel_package_to_publish_task(
        package=package,
        account=account,
        actor=None,
    )

    assert result.id == "pt-1"
    assert captured["content"].id == "content-1"
    assert captured["account"].id == "acc-1"
    assert captured["idempotency_key"] == "batch-delegated:pkg-1"
