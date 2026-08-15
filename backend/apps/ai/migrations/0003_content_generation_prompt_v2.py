from django.db import migrations


def _string(max_length):
    return {"type": "string", "minLength": 1, "maxLength": max_length}


def _string_list(max_items):
    return {
        "type": "array",
        "maxItems": max_items,
        "uniqueItems": True,
        "items": _string(256),
    }


def _common_variant_properties():
    return {
        "platform_code": _string(64),
        "language": _string(16),
        "title": _string(500),
        "body": _string(50_000),
        "cta": _string(2_000),
        "landing_page_url": _string(2_000),
        "hashtags": _string_list(30),
        "evidence_fact_ids": _string_list(100),
    }


def _common_variant_schema():
    properties = _common_variant_properties()
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "platform_code", "language", "title", "body", "cta",
            "landing_page_url", "hashtags", "evidence_fact_ids",
        ],
        "properties": properties,
    }


def _tiktok_variant_schema():
    properties = {
        **_common_variant_properties(),
        "duration_seconds": {"type": "integer", "minimum": 15, "maximum": 60},
        "aspect_ratio": {"const": "9:16"},
        "script": _string(50_000),
        "voiceover": _string(50_000),
        "subtitles": _string(50_000),
        "voiceover_language": _string(16),
        "subtitle_language": _string(16),
        "shot_list": {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scene", "visual", "on_screen_text"],
                "properties": {
                    "scene": _string(64),
                    "visual": _string(2_000),
                    "on_screen_text": _string(1_000),
                },
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "platform_code", "language", "title", "body", "cta",
            "landing_page_url", "hashtags", "evidence_fact_ids",
            "duration_seconds", "aspect_ratio", "script", "shot_list",
            "voiceover", "voiceover_language", "subtitles", "subtitle_language",
        ],
        "properties": properties,
    }


def _output_schema():
    properties = {
        "schema_version": {"const": 2},
        "language": _string(16),
        "title": _string(500),
        "body": _string(50_000),
        "cta": _string(2_000),
        "landing_page_url": _string(2_000),
        "concept_codes": _string_list(100),
        "evidence_fact_ids": _string_list(100),
        "internal_translation_zh": _string(50_000),
        "platform_variants": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "oneOf": [_common_variant_schema(), _tiktok_variant_schema()],
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "language", "title", "body", "cta",
            "landing_page_url", "concept_codes", "evidence_fact_ids",
            "platform_variants",
        ],
        "properties": properties,
    }


def add_content_prompt_v2(apps, schema_editor):
    del schema_editor
    PromptVersion = apps.get_model("ai", "PromptVersion")
    expected = {
        "purpose": "CONTENT_GENERATE",
        "code": "evidence-multichannel-v2",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "template": (
            "Generate one evidence-backed master and one materially adapted variant for "
            "every selected platform. Return only the requested JSON object."
        ),
        "output_schema": _output_schema(),
        "status": "PUBLISHED",
    }
    existing = PromptVersion.objects.filter(
        purpose="CONTENT_GENERATE", version=2,
    ).first()
    if existing is None:
        PromptVersion.objects.create(version=2, **expected)
        return
    if any(getattr(existing, key) != value for key, value in expected.items()):
        raise RuntimeError("CONTENT_GENERATE prompt version 2 conflicts with migration contract.")


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_add_airun_canceled_status"),
    ]

    operations = [
        migrations.RunPython(add_content_prompt_v2, migrations.RunPython.noop),
    ]
