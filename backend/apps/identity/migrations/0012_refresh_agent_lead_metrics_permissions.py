from django.db import migrations


NEW_PERMISSIONS = {
    "ADMINISTRATOR": [
        "agents.run",
        "agents.approve",
        "leads.read",
        "leads.manage",
        "metrics.read",
    ],
    "OPERATOR": [
        "agents.run",
        "agents.approve",
        "leads.read",
        "leads.manage",
        "metrics.read",
    ],
    "REVIEWER": [
        "agents.approve",
        "leads.read",
        "metrics.read",
    ],
    "READ_ONLY": [
        "metrics.read",
    ],
}


def refresh_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, permissions in NEW_PERMISSIONS.items():
        role = role_model.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(permission for permission in permissions if permission not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0011_organization_ai_daily_token_budget")]

    operations = [
        migrations.RunPython(refresh_permissions, migrations.RunPython.noop),
    ]
