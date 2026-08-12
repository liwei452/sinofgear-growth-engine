import hashlib
import json
import uuid

from django.db import migrations, models


def add_legacy_idempotency(apps, schema_editor):
    proposal_model = apps.get_model("director", "DirectorProposal")
    for proposal in proposal_model.objects.all().iterator():
        payload = {
            "proposal_type": proposal.proposal_type,
            "title_zh": proposal.title_zh,
            "summary_zh": proposal.summary_zh,
            "reason_snapshot": proposal.reason_snapshot,
            "action_reference": proposal.action_reference,
            "priority": proposal.priority,
            "expires_at": proposal.expires_at.isoformat() if proposal.expires_at else None,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        proposal.idempotency_key = f"legacy:{proposal.id}"
        proposal.request_fingerprint = hashlib.sha256(encoded).hexdigest()
        proposal.save(update_fields=["idempotency_key", "request_fingerprint"])


class Migration(migrations.Migration):
    dependencies = [
        ("director", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="directordecision",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AlterModelOptions(
            name="directorproposal",
            options={
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddField(
            model_name="directorproposal",
            name="idempotency_key",
            field=models.CharField(max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="directorproposal",
            name="request_fingerprint",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.RunPython(add_legacy_idempotency, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="directorproposal",
            name="idempotency_key",
            field=models.CharField(default=uuid.uuid4, max_length=128),
        ),
        migrations.AlterField(
            model_name="directorproposal",
            name="request_fingerprint",
            field=models.CharField(default="0" * 64, max_length=64),
        ),
        migrations.AddConstraint(
            model_name="directorproposal",
            constraint=models.UniqueConstraint(
                fields=("organization", "idempotency_key"),
                name="director_unique_proposal_idempotency",
            ),
        ),
    ]
