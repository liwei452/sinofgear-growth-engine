import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("campaigns", "0003_contentbrief_archived_at_contentbrief_archived_by_and_more"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentbrief",
            name="knowledge_context_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="content_briefs",
                to="knowledge.knowledgecontextsnapshot",
            ),
        ),
    ]
