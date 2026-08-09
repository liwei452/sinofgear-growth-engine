from django.db import migrations, models


def seed_is_a_graph_lock(apps, schema_editor) -> None:
    graph_lock = apps.get_model("knowledge", "KnowledgeGraphLock")
    graph_lock.objects.update_or_create(id=1, defaults={"name": "is_a_graph"})


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="KnowledgeGraphLock",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(default="is_a_graph", max_length=32, unique=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1),
                        name="knowledge_single_is_a_graph_lock",
                    )
                ]
            },
        ),
        migrations.RunPython(
            seed_is_a_graph_lock,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
