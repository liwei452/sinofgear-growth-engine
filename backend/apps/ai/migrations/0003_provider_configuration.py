import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_add_airun_canceled_status"),
        ("identity", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIProviderConfiguration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider_code", models.CharField(default="deepseek", editable=False, max_length=32)),
                ("connection_state", models.CharField(choices=[("NOT_CONFIGURED", "Not configured"), ("CONNECTED", "Connected")], default="NOT_CONFIGURED", max_length=24)),
                ("key_suffix", models.CharField(blank=True, max_length=4)),
                ("credential_revision", models.PositiveIntegerField(default=0)),
                ("last_tested_at", models.DateTimeField(blank=True, null=True)),
                ("daily_budget_usd", models.DecimalField(decimal_places=2, default=10, max_digits=10, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100000)])),
                ("flash_max_output_tokens", models.PositiveIntegerField(default=1200, validators=[django.core.validators.MinValueValidator(64), django.core.validators.MaxValueValidator(65536)])),
                ("pro_max_output_tokens", models.PositiveIntegerField(default=2400, validators=[django.core.validators.MinValueValidator(64), django.core.validators.MaxValueValidator(65536)])),
                ("timeout_seconds", models.PositiveSmallIntegerField(default=30, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(300)])),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_tested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tested_ai_provider_configurations", to=settings.AUTH_USER_MODEL)),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="ai_provider_configuration", to="identity.organization")),
            ],
            options={"ordering": ["organization_id"]},
        ),
    ]
