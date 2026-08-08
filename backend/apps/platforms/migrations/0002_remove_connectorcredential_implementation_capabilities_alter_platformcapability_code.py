# Generated manually for Task 4 review fixes.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platforms", "0001_initial")]

    operations = [
        migrations.RemoveField(model_name="connectorcredential", name="implementation_capabilities"),
        migrations.AlterField(
            model_name="platformcapability",
            name="code",
            field=models.CharField(
                choices=[
                    ("PUBLISH", "PUBLISH"),
                    ("METRICS_READ", "METRICS_READ"),
                    ("COMMENT_READ", "COMMENT_READ"),
                    ("PUBLIC_SEARCH", "PUBLIC_SEARCH"),
                    ("MEDIA_UPLOAD", "MEDIA_UPLOAD"),
                    ("WEBHOOK", "WEBHOOK"),
                ],
                max_length=32,
            ),
        ),
    ]
