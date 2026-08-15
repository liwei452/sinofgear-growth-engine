from copy import deepcopy

from django.db import migrations


def create_no_internal_translation_prompt(apps, schema_editor):
    PromptVersion = apps.get_model("ai", "PromptVersion")
    previous = PromptVersion.objects.get(
        purpose="CONTENT_GENERATE",
        code="evidence-multichannel-v3",
        version=3,
    )
    output_schema = deepcopy(previous.output_schema)
    output_schema["properties"].pop("internal_translation_zh", None)
    PromptVersion.objects.create(
        purpose="CONTENT_GENERATE",
        code="no-internal-translation-v4",
        version=4,
        provider=previous.provider,
        model=previous.model,
        template=previous.template,
        output_schema=output_schema,
        status="PUBLISHED",
    )


class Migration(migrations.Migration):
    dependencies = [("ai", "0004_content_generation_prompt_v3")]

    operations = [
        migrations.RunPython(
            create_no_internal_translation_prompt,
            migrations.RunPython.noop,
        ),
    ]
