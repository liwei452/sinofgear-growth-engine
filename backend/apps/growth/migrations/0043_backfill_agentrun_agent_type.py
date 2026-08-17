from django.db import migrations


def backfill_agent_runs(apps, schema_editor):
    AgentRun = apps.get_model("growth", "AgentRun")
    for run in AgentRun.objects.filter(agent_type="").iterator():
        key = run.idempotency_key
        if key.startswith("proactive:"):
            run.agent_type = "proactive"
            run.resume_args = {"candidate_id": key.split(":", 1)[1]}
        elif key.startswith("content-strategy:"):
            run.agent_type = "content_strategy"
            run.resume_args = {"creator_id": None}
        elif key.startswith("content-creation:"):
            run.agent_type = "content_creation"
            run.resume_args = {
                "brief_id": key.split(":", 1)[1],
                "actor_id": None,
                "values": {},
                "product_id": "",
                "platform_id": "",
            }
        elif key.startswith("platform-variants:"):
            run.agent_type = "platform_variants"
            run.resume_args = {"master_id": key.split(":", 1)[1], "actor_id": None}
        elif key.startswith("social-ops:"):
            parts = key.split(":")
            run.agent_type = "social_ops"
            run.resume_args = {
                "content_id": parts[1] if len(parts) > 1 else "",
                "account_id": parts[2] if len(parts) > 2 else "",
                "scheduled_at": None,
                "timezone_name": "UTC",
                "idempotency_key": None,
            }
        elif key.startswith("customer-service:"):
            run.agent_type = "customer_service"
            run.resume_args = {"rfq_id": key.split(":", 1)[1]}
        else:
            continue
        run.save(update_fields=["agent_type", "resume_args"])


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0042_remove_customerserviceturn_growth_unique_customer_service_turn_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_agent_runs, migrations.RunPython.noop),
    ]
