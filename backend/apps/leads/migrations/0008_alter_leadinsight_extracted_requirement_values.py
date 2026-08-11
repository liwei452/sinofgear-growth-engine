from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0007_leadanalysisbinding_leadreview_and_more")]

    operations = [
        migrations.AlterField(
            model_name="leadinsight",
            name="extracted_requirement_values",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
