import pytest

from integrations.platforms.manual_fake import (
    ExternalPublishDisabled,
    ManualPackageFakeConnector,
    simulate_publish,
)


def test_tiktok_package_enforces_manual_video_contract():
    connector = ManualPackageFakeConnector()
    payload = {
        "duration_seconds": 30,
        "aspect_ratio": "9:16",
        "script": "A 30 second evidence-led script",
        "shot_list": ["gear close-up", "inspection report"],
        "english_voiceover": "See how each gear is inspected.",
        "chinese_subtitles": "查看每个齿轮如何检测。",
        "title": "Precision gear inspection",
        "hashtags": ["gears", "manufacturing"],
        "cta": "Review the capability summary",
        "utm": "utm_source=tiktok&utm_medium=organic",
    }

    receipt = connector.build_package(channel="TIKTOK", payload=payload)

    assert receipt.mode == "MANUAL_PACKAGE"
    assert receipt.data_label == "Demo / Fake"
    assert receipt.payload == payload
    with pytest.raises(ValueError, match="15 and 60"):
        connector.build_package(channel="TIKTOK", payload={**payload, "duration_seconds": 61})
    with pytest.raises(ValueError, match="9:16"):
        connector.build_package(channel="TIKTOK", payload={**payload, "aspect_ratio": "16:9"})


def test_fake_connector_cannot_publish_externally():
    connector = ManualPackageFakeConnector()

    with pytest.raises(ExternalPublishDisabled, match="approved OAuth"):
        connector.publish({"content": "must not leave the process"})


def test_simulated_publish_is_deterministic_and_never_returns_a_real_url():
    first = simulate_publish(
        channel="LINKEDIN",
        payload={"title": "Inspection proof"},
        item_id="00000000-0000-4000-8000-000000000001",
        attempt_number=1,
        outcome="success",
        is_demo=True,
    )
    second = simulate_publish(
        channel="LINKEDIN",
        payload={"title": "Inspection proof"},
        item_id="00000000-0000-4000-8000-000000000001",
        attempt_number=2,
        outcome="success",
        is_demo=True,
    )

    assert first.succeeded is True
    assert second.external_id == first.external_id
    assert first.external_url == "https://example.invalid/demo-post/linkedin/00000000-0000-4000-8000-000000000001"
    assert first.data_label == "Demo / Fake"
    with pytest.raises(ExternalPublishDisabled, match="Demo packages"):
        simulate_publish(
            channel="LINKEDIN", payload={}, item_id="real", attempt_number=1,
            outcome="success", is_demo=False,
        )


def test_simulated_fail_once_succeeds_on_retry():
    failed = simulate_publish(
        channel="TIKTOK", payload={"title": "Video"}, item_id="item-1",
        attempt_number=1, outcome="fail_once", is_demo=True,
    )
    retried = simulate_publish(
        channel="TIKTOK", payload={"title": "Video"}, item_id="item-1",
        attempt_number=2, outcome="fail_once", is_demo=True,
    )

    assert failed.succeeded is False
    assert failed.error_code == "PROVIDER_ERROR"
    assert retried.succeeded is True
