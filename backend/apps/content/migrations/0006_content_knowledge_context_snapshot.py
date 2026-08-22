import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0005_mastercontent_archived_at_mastercontent_archived_by_and_more"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]

    operations = [
        migrations.AddField(
            model_name="mastercontent",
            name="knowledge_context_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="master_contents",
                to="knowledge.knowledgecontextsnapshot",
            ),
        ),
        migrations.AddField(
            model_name="platformcontent",
            name="knowledge_context_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="platform_contents",
                to="knowledge.knowledgecontextsnapshot",
            ),
        ),
    ]
