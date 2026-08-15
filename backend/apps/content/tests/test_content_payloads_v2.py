import pytest

from apps.content import payloads


def _snapshot():
    return {
        "language": "id",
        "target_platforms": [
            {"code": "LINKEDIN"},
            {"code": "FACEBOOK"},
            {"code": "INSTAGRAM"},
            {"code": "TIKTOK"},
        ],
        "verified_product_facts": [{"fact_id": "fact-1"}],
        "ontology_snapshot": {
            "concept_versions": [{"code": "HELICAL_GEAR", "status": "APPROVED"}],
        },
    }


def _variant(code, body):
    result = {
        "platform_code": code,
        "language": "id",
        "title": f"{code} title",
        "body": body,
        "cta": "Minta penawaran",
        "landing_page_url": "https://example.com/id/gears",
        "hashtags": ["#GearManufacturing"],
        "evidence_fact_ids": ["fact-1"],
    }
    if code == "TIKTOK":
        result.update({
            "duration_seconds": 42,
            "aspect_ratio": "9:16",
            "script": "Naskah TikTok bahasa Indonesia",
            "shot_list": [{
                "scene": "1",
                "visual": "Close-up pemeriksaan roda gigi",
                "on_screen_text": "Pemeriksaan presisi",
            }],
            "voiceover": "Sulih suara bahasa Indonesia",
            "voiceover_language": "id",
            "subtitles": "Teks bahasa Indonesia",
            "subtitle_language": "id",
        })
    return result


def _output():
    return {
        "schema_version": 2,
        "language": "id",
        "title": "Solusi roda gigi presisi",
        "body": "Konten utama untuk pembeli industri.",
        "cta": "Minta penawaran",
        "landing_page_url": "https://example.com/id/gears",
        "concept_codes": ["HELICAL_GEAR"],
        "evidence_fact_ids": ["fact-1"],
        "internal_translation_zh": "仅供内部审核的中文释义",
        "platform_variants": [
            _variant("LINKEDIN", "LinkedIn Indonesia body"),
            _variant("FACEBOOK", "Facebook Indonesia body"),
            _variant("INSTAGRAM", "Instagram Indonesia body"),
            _variant("TIKTOK", "TikTok Indonesia body"),
        ],
    }


def test_version_two_payload_accepts_one_language_and_exact_platform_variants():
    cleaned = payloads.validate_generated_content_output(_output(), _snapshot())

    assert cleaned["language"] == "id"
    assert [row["platform_code"] for row in cleaned["platform_variants"]] == [
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK",
    ]
    assert cleaned["platform_variants"][3]["duration_seconds"] == 42


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda output: output["platform_variants"][0].update(language="en"), "language"),
        (lambda output: output["platform_variants"].pop(), "platform"),
        (lambda output: output["evidence_fact_ids"].append("unknown"), "evidence"),
        (lambda output: output["platform_variants"][3].update(duration_seconds=61), "payload"),
        (lambda output: output["platform_variants"][3].update(shot_list=[]), "payload"),
    ],
)
def test_version_two_payload_fails_closed_for_unpublishable_output(mutation, message):
    output = _output()
    mutation(output)

    with pytest.raises(ValueError, match=message):
        payloads.validate_generated_content_output(output, _snapshot())


def test_platform_payload_never_contains_internal_chinese_reference():
    master = payloads.validate_generated_content_output(_output(), _snapshot())

    platform = payloads.platform_variant_payload(master, "TIKTOK")

    assert platform["language"] == "id"
    assert "internal_translation_zh" not in platform
    assert platform["voiceover_language"] == platform["subtitle_language"] == "id"
