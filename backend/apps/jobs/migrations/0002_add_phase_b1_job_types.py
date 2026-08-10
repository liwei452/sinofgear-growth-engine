from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("jobs", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="job",
            name="type",
            field=models.CharField(
                choices=[
                    ("CONTENT_GENERATE", "Content generate"),
                    ("SOURCE_IMPORT", "Source import"),
                    ("SOURCE_NORMALIZE", "Source normalize"),
                    ("EVIDENCE_EXTRACT", "Evidence extract"),
                    ("LEAD_ANALYZE", "Lead analyze"),
                    ("RETENTION_CLEANUP", "Retention cleanup"),
                ],
                max_length=32,
            ),
        )
    ]
