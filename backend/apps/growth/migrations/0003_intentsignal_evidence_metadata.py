from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("growth", "0002_growthpublishbatch_growthpublishitem_and_more")]

    operations = [
        migrations.AddField(
            model_name="intentsignal",
            name="collection_method",
            field=models.CharField(default="DEMO_FIXTURE", max_length=32),
        ),
        migrations.AddField(
            model_name="intentsignal",
            name="content_hash",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="intentsignal",
            name="score_breakdown",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="intentsignal",
            name="scoring_rule_version",
            field=models.CharField(default="opportunity-v1", max_length=64),
        ),
        migrations.AddField(
            model_name="intentsignal",
            name="uncertainty_notes",
            field=models.JSONField(default=list),
        ),
    ]
