from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("growth", "0017_channelpackage_source_platform_content")]

    operations = [
        migrations.AddField(
            model_name="fieldprovenance",
            name="is_demo",
            field=models.BooleanField(default=False),
        ),
    ]
