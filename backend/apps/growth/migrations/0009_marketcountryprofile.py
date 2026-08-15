import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0008_intentsignal_evidence_envelope"),
        ("identity", "0010_phaseae2eownership"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketCountryProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("country_code", models.CharField(max_length=3)),
                ("country_label", models.CharField(max_length=96)),
                ("status", models.CharField(choices=[("OBSERVATION_POOL", "Observation pool"), ("DATA_VALIDATION", "Data validation"), ("SMALL_PILOT", "Small pilot"), ("ACTIVE_MARKET", "Active market"), ("PAUSED", "Paused")], max_length=24)),
                ("route", models.CharField(max_length=48)),
                ("route_label", models.CharField(max_length=128)),
                ("recommended_wave", models.CharField(max_length=64)),
                ("priority_order", models.PositiveSmallIntegerField()),
                ("source_types", models.JSONField(default=list)),
                ("last_researched_at", models.DateField()),
                ("scores", models.JSONField(default=dict)),
                ("sample_quality", models.JSONField(default=dict)),
                ("recommendation_reasons", models.JSONField(default=list)),
                ("hold_reasons", models.JSONField(default=list)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="identity.organization")),
            ],
            options={"ordering": ["priority_order", "country_code"]},
        ),
        migrations.AddConstraint(
            model_name="marketcountryprofile",
            constraint=models.UniqueConstraint(fields=("organization", "country_code"), name="growth_unique_market_country"),
        ),
    ]
