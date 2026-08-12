from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_usage_pricing")]

    operations = [
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
        migrations.AddConstraint(
            model_name="aiusageattempt",
            constraint=models.CheckConstraint(
                condition=models.Q(("additional_reserved_usd__gte", 0)),
                name="ai_usage_attempt_extra_reserved_nonnegative",
            ),
        ),
    ]
