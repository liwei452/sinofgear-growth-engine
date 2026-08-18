from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("growth", "0044_agentrun_approval_comment_agentrun_approved_at_and_more")]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="execution_mode",
            field=models.CharField(
                choices=[
                    ("AUTOMATION", "Automation"),
                    ("AI_AGENT", "AI agent"),
                    ("AI_GENERATION", "AI generation"),
                ],
                default="AUTOMATION",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="planner_model",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="planner_provider",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
