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


def test_sync_publish_item_from_task_marks_success(db, monkeypatch):
    from apps.growth import publishing as gp

    class FakeItem:
        def __init__(self):
            self.status = "DELEGATED"
            self.external_post_id = ""
            self.last_error = None
            self.batch = SimpleNamespace(refresh_from_db=lambda: None)

        def save(self, update_fields=None):
            self.update_fields = update_fields

    item = FakeItem()
    monkeypatch.setattr(
        gp,
        "GrowthPublishItem",
        SimpleNamespace(
            Status=SimpleNamespace(
                SUCCEEDED="SUCCEEDED",
                FAILED="FAILED",
                DELEGATED="DELEGATED",
            ),
            objects=SimpleNamespace(
                select_for_update=lambda: SimpleNamespace(
                    filter=lambda **kwargs: SimpleNamespace(first=lambda: item)
                )
            )
        ),
    )
    monkeypatch.setattr(
        gp,
        "PublishTask",
        SimpleNamespace(
            Status=SimpleNamespace(SUCCEEDED="SUCCEEDED", FAILED="FAILED"),
            objects=SimpleNamespace(
                filter=lambda **kwargs: SimpleNamespace(
                    first=lambda: SimpleNamespace(id="task-1", status="SUCCEEDED")
                )
            ),
        ),
    )
    monkeypatch.setattr(
        gp,
        "PublishedPost",
        SimpleNamespace(
            objects=SimpleNamespace(
                filter=lambda **kwargs: SimpleNamespace(
                    first=lambda: SimpleNamespace(external_id="post-1")
                )
            )
        ),
    )
    monkeypatch.setattr(gp, "_refresh_batch_status", lambda batch: batch)

    result = gp.sync_publish_item_from_task(task_id="task-1")

    assert result is item
    assert item.status == "SUCCEEDED"
    assert item.external_post_id == "post-1"


def test_sync_publish_item_from_task_marks_canceled(db, monkeypatch):
    from apps.growth import publishing as gp

    class FakeItem:
        def __init__(self):
            self.status = "DELEGATED"
            self.external_post_id = ""
            self.last_error = None
            self.batch = SimpleNamespace(refresh_from_db=lambda: None)

        def save(self, update_fields=None):
            self.update_fields = update_fields

    item = FakeItem()
    monkeypatch.setattr(
        gp,
        "GrowthPublishItem",
        SimpleNamespace(
            Status=SimpleNamespace(SUCCEEDED="SUCCEEDED", FAILED="FAILED"),
            objects=SimpleNamespace(
                select_for_update=lambda: SimpleNamespace(
                    filter=lambda **kwargs: SimpleNamespace(first=lambda: item)
                )
            ),
        ),
    )
    monkeypatch.setattr(
        gp,
        "PublishTask",
        SimpleNamespace(
            Status=SimpleNamespace(
                SUCCEEDED="SUCCEEDED", FAILED="FAILED", CANCELED="CANCELED",
            ),
            objects=SimpleNamespace(
                filter=lambda **kwargs: SimpleNamespace(
                    first=lambda: SimpleNamespace(id="task-1", status="CANCELED")
                )
            ),
        ),
    )
    monkeypatch.setattr(
        gp,
        "PublishedPost",
        SimpleNamespace(
            objects=SimpleNamespace(
                filter=lambda **kwargs: SimpleNamespace(first=lambda: None)
            )
        ),
    )
    monkeypatch.setattr(gp, "_refresh_batch_status", lambda batch: batch)

    result = gp.sync_publish_item_from_task(task_id="task-1")

    assert result is item
    assert item.status == "FAILED"
    assert item.last_error["code"] == "PUBLISH_CANCELED"
