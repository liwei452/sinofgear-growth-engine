import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0048_alter_missionentitylink_entity_type"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="knowledge_context_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="agent_runs",
                to="knowledge.knowledgecontextsnapshot",
            ),
        ),
        migrations.AddField(
            model_name="outreachdraft",
            name="knowledge_context_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="outreach_drafts",
                to="knowledge.knowledgecontextsnapshot",
            ),
        ),
    ]
