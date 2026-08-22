import pytest

from apps.content import payloads


def _snapshot():
    return {
        "language": "id",
        "landing_page_url": "https://example.com/id/gears",
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
        (lambda output: output["evidence_fact_ids"].clear(), "evidence"),
        (lambda output: output["evidence_fact_ids"].append("unknown"), "evidence"),
        (lambda output: output["platform_variants"][0]["evidence_fact_ids"].clear(), "evidence"),
        (lambda output: output.update(landing_page_url="https://evil.example/redirect"), "landing"),
        (lambda output: output["platform_variants"][0].update(landing_page_url="https://evil.example/redirect"), "landing"),
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


@pytest.mark.parametrize("language", ["id", "zh-CN"])
def test_new_generation_rejects_internal_chinese_translation(language):
    output = _output()
    snapshot = _snapshot()
    output["language"] = language
    snapshot["language"] = language
    for variant in output["platform_variants"]:
        variant["language"] = language
        if variant["platform_code"] == "TIKTOK":
            variant["voiceover_language"] = language
            variant["subtitle_language"] = language
    output["internal_translation_zh"] = "不得生成的内部翻译"

    with pytest.raises(ValueError, match="internal_translation_zh"):
        payloads.validate_generated_content_output(output, snapshot)


def test_historical_version_two_payload_with_translation_remains_readable():
    historical = _output()
    historical["internal_translation_zh"] = "历史内部翻译"

    cleaned = payloads.validate_content_payload(historical)

    assert cleaned["internal_translation_zh"] == "历史内部翻译"


def test_version_two_schema_requires_evidence_for_master_and_platforms():
    assert payloads.CONTENT_OUTPUT_SCHEMA_V2["properties"]["evidence_fact_ids"]["minItems"] == 1
    assert payloads.PLATFORM_VARIANT_V2_SCHEMA["properties"]["evidence_fact_ids"]["minItems"] == 1
    assert "internal_translation_zh" not in payloads.CONTENT_OUTPUT_SCHEMA_V2["properties"]


def test_generated_output_rejects_prohibited_claims():
    snapshot = {
        **_snapshot(),
        "prohibited_claims": ["guaranteed zero wear"],
    }
    output = _output()
    output["body"] = "This gear set comes with guaranteed zero wear."

    with pytest.raises(ValueError, match="prohibited claim"):
        payloads.validate_generated_content_output(output, snapshot)


def test_generated_output_rejects_prohibited_claims_in_platform_copy():
    snapshot = {
        **_snapshot(),
        "prohibited_claims": ["PRECISION GROUND TEETH"],
    }
    output = _output()
    output["platform_variants"][0]["body"] = "Precision ground teeth for mining equipment."

    with pytest.raises(ValueError, match="prohibited claim"):
        payloads.validate_generated_content_output(output, snapshot)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda output: output["platform_variants"][0].update(
            hashtags=["guaranteed zero wear"]
        ),
        lambda output: output["platform_variants"][3]["shot_list"][0].update(
            visual="Show guaranteed zero wear on the product badge"
        ),
    ],
)
def test_generated_output_rejects_prohibited_claims_in_all_platform_fields(mutation):
    snapshot = {
        **_snapshot(),
        "prohibited_claims": ["guaranteed zero wear"],
    }
    output = _output()
    mutation(output)

    with pytest.raises(ValueError, match="prohibited claim"):
        payloads.validate_generated_content_output(output, snapshot)


def test_generated_output_rejects_numeric_claim_without_verified_fact():
    snapshot = {
        **_snapshot(),
        "verified_product_facts": [{"fact_id": "fact-1", "value": "18"}],
    }
    output = _output()
    output["body"] = "Our gears are available with 20 teeth."

    with pytest.raises(ValueError, match="numeric claim"):
        payloads.validate_generated_content_output(output, snapshot)


def test_generated_output_accepts_numeric_claim_backed_by_verified_fact():
    snapshot = {
        **_snapshot(),
        "verified_product_facts": [{"fact_id": "fact-1", "value": "20 teeth"}],
    }
    output = _output()
    output["body"] = "Our gears are available with 20 teeth."

    cleaned = payloads.validate_generated_content_output(output, snapshot)

    assert cleaned["body"] == "Our gears are available with 20 teeth."


def test_numeric_grounding_does_not_match_substring_of_larger_number():
    snapshot = {
        **_snapshot(),
        "verified_product_facts": [{"fact_id": "fact-1", "value": "20"}],
    }
    output = _output()
    output["body"] = "Our gears run at 1200 rpm."

    with pytest.raises(ValueError, match="numeric claim"):
        payloads.validate_generated_content_output(output, snapshot)


@pytest.mark.parametrize(
    ("fact_id", "accepted"),
    [("public-company-fact", True), ("internal-company-fact", False)],
)
def test_external_evidence_accepts_only_snapshot_public_claim_ids(fact_id, accepted):
    snapshot = {
        **_snapshot(),
        "agent_context": {
            "seller": {
                "public_claims": [{"fact_id": "public-company-fact"}],
            }
        },
    }
    output = _output()
    output["evidence_fact_ids"] = [fact_id]
    for variant in output["platform_variants"]:
        variant["evidence_fact_ids"] = [fact_id]

    if accepted:
        assert payloads.validate_generated_content_output(output, snapshot)
    else:
        with pytest.raises(ValueError, match="unknown fact"):
            payloads.validate_generated_content_output(output, snapshot)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda output: output.update(title="Review https://attacker.example/offer"),
        lambda output: output["platform_variants"][0].update(
            cta="Review https://attacker.example/offer"
        ),
    ],
)
def test_generated_output_rejects_unverified_urls_in_any_outbound_text(mutate):
    output = _output()
    mutate(output)

    with pytest.raises(ValueError, match="verified URL"):
        payloads.validate_generated_content_output(output, _snapshot())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda variant: variant.update(evidence_fact_ids=["unknown"]), "unknown fact"),
        (
            lambda variant: variant.update(title="Guaranteed zero wear"),
            "prohibited claim",
        ),
        (
            lambda variant: variant.update(body="See https://attacker.example/offer"),
            "verified URL",
        ),
    ],
)
def test_snapshot_bound_platform_revision_revalidates_all_external_fields(
    mutation, message
):
    snapshot = {**_snapshot(), "prohibited_claims": ["guaranteed zero wear"]}
    variant = {"schema_version": 2, **_variant("LINKEDIN", "LinkedIn Indonesia body")}
    mutation(variant)

    with pytest.raises(ValueError, match=message):
        payloads.validate_snapshot_bound_platform_output(
            variant,
            snapshot,
            platform_code="LINKEDIN",
        )


@pytest.mark.parametrize(
    "field",
    [
        "hashtags",
        "script",
        "voiceover",
        "subtitles",
        "scene",
        "visual",
        "on_screen_text",
    ],
)
@pytest.mark.parametrize(
    ("unsafe_text", "message"),
    [
        ("Guaranteed zero wear", "prohibited claim"),
        ("Review https://attacker.example/offer", "verified URL"),
        ("Guaranteed operation at 200 rpm", "numeric claim"),
    ],
)
def test_snapshot_bound_tiktok_revision_scans_every_standalone_platform_field(
    field, unsafe_text, message
):
    snapshot = {
        **_snapshot(),
        "prohibited_claims": ["guaranteed zero wear"],
        "verified_product_facts": [{"fact_id": "fact-1", "value": "18 teeth"}],
    }
    variant = {"schema_version": 2, **_variant("TIKTOK", "TikTok Indonesia body")}
    if field == "hashtags":
        variant[field] = [unsafe_text]
    elif field in {"scene", "visual", "on_screen_text"}:
        variant["shot_list"][0][field] = unsafe_text
    else:
        variant[field] = unsafe_text

    with pytest.raises(ValueError, match=message):
        payloads.validate_snapshot_bound_platform_output(
            variant,
            snapshot,
            platform_code="TIKTOK",
        )
