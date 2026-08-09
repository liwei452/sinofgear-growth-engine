import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0009_refresh_tracking_permissions")]

    operations = [
        migrations.CreateModel(
            name="PhaseAE2EOwnership",
            fields=[
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="phase_a_e2e_ownership",
                        serialize=False,
                        to="identity.organization",
                    ),
                ),
                ("nonce", models.CharField(max_length=64)),
                ("signature", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
