from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("growth", "0007_official_procurement_source")]

    operations = [
        migrations.AddField(
            model_name="intentsignal",
            name="evidence_envelope",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
