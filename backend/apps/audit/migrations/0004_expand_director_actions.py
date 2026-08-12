from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0003_auditlog_actor_nullable"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approvalrecord",
            name="action",
            field=models.CharField(
                choices=[
                    ("SUBMIT", "Submit for review"),
                    ("APPROVE", "Approve"),
                    ("REJECT", "Reject"),
                    ("DEPRECATE", "Deprecate"),
                    ("ARCHIVE", "Archive"),
                    ("REQUEST_ADJUSTMENT", "Request adjustment"),
                    ("SUPERSEDE", "Supersede"),
                ],
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("SUBMIT", "Submit for review"),
                    ("APPROVE", "Approve"),
                    ("REJECT", "Reject"),
                    ("DEPRECATE", "Deprecate"),
                    ("ARCHIVE", "Archive"),
                    ("REQUEST_ADJUSTMENT", "Request adjustment"),
                    ("SUPERSEDE", "Supersede"),
                ],
                max_length=24,
            ),
        ),
    ]
