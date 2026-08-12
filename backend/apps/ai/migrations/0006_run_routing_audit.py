import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_usage_pricing")]

    operations = [
        migrations.AddField(
            model_name="aiexecutionintent", name="provider_input_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="aiexecutionintent", name="provider_prompt",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="aiexecutionintent", name="provider_schema",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="aiexecutionintent", name="prompt_purpose",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="aiexecutionintent", name="prompt_version_id_snapshot",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aiusageattempt",
            name="additional_reserved_usd",
            field=models.DecimalField(decimal_places=6, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name="airun",
            name="transport_retry_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="airun",
            name="repair_attempted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="airun",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="airun", name="next_call_generation",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="airun", name="next_call_phase",
            field=models.CharField(default="NORMAL", max_length=12),
        ),
        migrations.AddField(
            model_name="airun", name="retry_dispatch_token",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="aiusageattempt",
            constraint=models.CheckConstraint(
                condition=models.Q(("additional_reserved_usd__gte", 0)),
                name="ai_usage_attempt_extra_reserved_nonnegative",
            ),
        ),
        migrations.CreateModel(
            name="AIProviderCall",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("generation", models.PositiveSmallIntegerField()),
                ("phase", models.CharField(choices=[("NORMAL", "Normal"), ("REPAIR", "Repair")], default="NORMAL", max_length=12)),
                ("status", models.CharField(choices=[("RESERVED", "Reserved"), ("CALLING", "Calling"), ("SUCCEEDED", "Succeeded"), ("FAILED", "Failed"), ("AMBIGUOUS", "Ambiguous"), ("CANCELED_PRE_CALL", "Canceled before call")], max_length=24)),
                ("lease_token", models.UUIDField(blank=True, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("reserved_usd", models.DecimalField(decimal_places=6, max_digits=12)),
                ("actual_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("request_id", models.CharField(blank=True, max_length=128)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("cache_hit_tokens", models.PositiveIntegerField(default=0)),
                ("finish_reason", models.CharField(blank=True, max_length=64)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="provider_calls", to="ai.airun")),
            ],
            options={
                "ordering": ["run_id", "generation"],
                "constraints": [
                    models.UniqueConstraint(fields=("run", "generation"), name="ai_unique_provider_call_generation"),
                    models.CheckConstraint(condition=models.Q(("actual_usd__gte", 0), ("reserved_usd__gte", 0)), name="ai_provider_call_cost_nonnegative"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AIRetryDispatchOutbox",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("retry_generation", models.PositiveSmallIntegerField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("DISPATCHING", "Dispatching"), ("ACKED", "Acknowledged")], default="PENDING", max_length=16)),
                ("available_at", models.DateTimeField()),
                ("lease_token", models.UUIDField(blank=True, null=True)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="retry_outbox", to="ai.airun")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("run", "retry_generation"), name="ai_unique_retry_outbox_generation")],
            },
        ),
    ]
