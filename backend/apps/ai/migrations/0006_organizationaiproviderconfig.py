import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0005_remove_internal_translation_from_generation"),
        ("identity", "0014_organization_ai_daily_reserved_on_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationAIProviderConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(default="deepseek", max_length=32)),
                ("model", models.CharField(default="deepseek-chat", max_length=64)),
                ("encrypted_api_key", models.TextField(blank=True, default="")),
                ("enabled", models.BooleanField(default=False)),
                ("daily_budget_micros", models.PositiveBigIntegerField(blank=True, null=True)),
                ("daily_spent_micros", models.PositiveBigIntegerField(default=0)),
                ("daily_reserved_micros", models.PositiveBigIntegerField(default=0)),
                ("spent_on", models.DateField(blank=True, null=True)),
                ("last_tested_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, default="", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ai_provider_config",
                        to="identity.organization",
                    ),
                ),
            ],
            options={"ordering": ["organization_id"]},
        ),
    ]
