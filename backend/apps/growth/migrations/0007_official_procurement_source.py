from django.db import migrations, models


def use_official_procurement_source(apps, schema_editor):
    discovery_profile = apps.get_model("growth", "DiscoveryProfile")
    discovery_profile.objects.filter(source_code="TED").update(
        source_code="OFFICIAL_PROCUREMENT",
    )


class Migration(migrations.Migration):
    dependencies = [("growth", "0006_remove_targetaccount_growth_unique_account_name_and_more")]

    operations = [
        migrations.RunPython(
            use_official_procurement_source,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="discoveryprofile",
            name="source_code",
            field=models.CharField(default="OFFICIAL_PROCUREMENT", max_length=32),
        ),
    ]
