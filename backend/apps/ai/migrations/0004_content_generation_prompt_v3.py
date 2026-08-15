from copy import deepcopy

from django.db import migrations


def create_strict_content_prompt(apps, schema_editor):
    PromptVersion = apps.get_model("ai", "PromptVersion")
    previous = PromptVersion.objects.get(
        purpose="CONTENT_GENERATE",
        code="evidence-multichannel-v2",
        version=2,
    )
    output_schema = deepcopy(previous.output_schema)
    output_schema["properties"]["evidence_fact_ids"]["minItems"] = 1
    for variant_schema in output_schema["properties"]["platform_variants"]["items"]["oneOf"]:
        variant_schema["properties"]["evidence_fact_ids"]["minItems"] = 1
    PromptVersion.objects.create(
        purpose="CONTENT_GENERATE",
        code="evidence-multichannel-v3",
        version=3,
        provider=previous.provider,
        model=previous.model,
        template=previous.template,
        output_schema=output_schema,
        status="PUBLISHED",
    )


class Migration(migrations.Migration):
    dependencies = [("ai", "0003_content_generation_prompt_v2")]

    operations = [migrations.RunPython(create_strict_content_prompt, migrations.RunPython.noop)]
