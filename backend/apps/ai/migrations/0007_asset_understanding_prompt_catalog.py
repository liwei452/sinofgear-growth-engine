from django.db import migrations
from django.db.models import Max


PURPOSE = "ASSET_UNDERSTAND"
PROMPT_CODE = "asset-understand-evidence-v1"
TEMPLATE = "Extract only literal product facts with exact page and excerpt evidence."
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "field_name": {"type": "string", "maxLength": 64},
                    "value": {"type": "string", "maxLength": 1000},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "source_page": {"type": "integer", "minimum": 1, "maximum": 30},
                    "source_excerpt": {"type": "string", "maxLength": 2000},
                },
                "required": [
                    "field_name", "value", "confidence", "source_page", "source_excerpt",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["facts"],
    "additionalProperties": False,
}


def _require_prompt_catalog_owner(schema_editor):
    if schema_editor is None or schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT tableowner = current_user FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = 'ai_promptversion'"
        )
        row = cursor.fetchone()
    if row != (True,):
        raise RuntimeError(
            "Asset prompt catalog migration requires the migration owner role."
        )


def seed_asset_understanding_prompt(apps, schema_editor):
    _require_prompt_catalog_owner(schema_editor)
    prompt_version = apps.get_model("ai", "PromptVersion")
    existing = list(
        prompt_version.objects.filter(purpose=PURPOSE, code=PROMPT_CODE).order_by("version")
    )
    if existing:
        compatible = all(
            prompt.template == TEMPLATE
            and prompt.output_schema == OUTPUT_SCHEMA
            and prompt.status == "PUBLISHED"
            for prompt in existing
        )
        if not compatible:
            raise RuntimeError(
                "Asset understanding prompt catalog entry conflicts with the system contract."
            )
        return

    latest = (
        prompt_version.objects.filter(purpose=PURPOSE).aggregate(value=Max("version"))["value"]
        or 0
    )
    prompt_version.objects.create(
        purpose=PURPOSE,
        code=PROMPT_CODE,
        version=latest + 1,
        provider="system",
        model="provider-agnostic",
        template=TEMPLATE,
        output_schema=OUTPUT_SCHEMA,
        status="PUBLISHED",
        created_by=None,
    )


class Migration(migrations.Migration):
    dependencies = [("ai", "0006_organizationaiproviderconfig")]

    operations = [
        migrations.RunPython(seed_asset_understanding_prompt, migrations.RunPython.noop),
    ]
