import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("growth", "0010_opportunityreview_crmhandoff")]

    operations = [
        migrations.CreateModel(
            name="DiscoveryCandidate",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company_name", models.CharField(max_length=255)),
                ("country", models.CharField(max_length=96)),
                ("website", models.URLField(blank=True)),
                ("industry", models.CharField(blank=True, max_length=160)),
                ("status", models.CharField(choices=[("PENDING_REVIEW", "Pending review"), ("ACCEPTED", "Accepted"), ("DISMISSED", "Dismissed")], default="PENDING_REVIEW", max_length=24)),
                ("import_format", models.CharField(max_length=16)),
                ("source_governance", models.JSONField(default=dict)),
                ("raw_record", models.JSONField(default=dict)),
                ("record_hash", models.CharField(max_length=64)),
                ("is_demo", models.BooleanField(default=False)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="identity.organization")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="discoverycandidate",
            constraint=models.UniqueConstraint(fields=("organization", "record_hash"), name="growth_unique_discovery_candidate_hash"),
        ),
    ]
