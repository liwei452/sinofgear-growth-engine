import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("growth", "0009_marketcountryprofile"),
    ]

    operations = [
        migrations.CreateModel(
            name="OpportunityReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("decision", models.CharField(choices=[("PRIORITIZE", "Prioritize"), ("OBSERVE", "Observe"), ("PROCESSED", "Processed")], max_length=16)),
                ("reason", models.CharField(max_length=255)),
                ("original_confidence", models.PositiveSmallIntegerField()),
                ("original_score_breakdown", models.JSONField(default=dict)),
                ("account", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="opportunity_reviews", to="growth.targetaccount")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="identity.organization")),
                ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="growth_opportunity_reviews", to=settings.AUTH_USER_MODEL)),
                ("signal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="opportunity_reviews", to="growth.intentsignal")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="CRMHandoff",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("connector", models.CharField(default="MOCK_CRM", max_length=32)),
                ("status", models.CharField(default="RECORDED", max_length=24)),
                ("payload_snapshot", models.JSONField(default=dict)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="growth_crm_handoffs", to=settings.AUTH_USER_MODEL)),
                ("draft", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="crm_handoffs", to="growth.outreachdraft")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="identity.organization")),
                ("review", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="crm_handoffs", to="growth.opportunityreview")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="crmhandoff",
            constraint=models.UniqueConstraint(fields=("organization", "review"), name="growth_one_crm_handoff_per_review"),
        ),
    ]
