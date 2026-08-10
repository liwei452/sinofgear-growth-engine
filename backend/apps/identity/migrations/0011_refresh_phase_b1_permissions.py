from django.db import migrations


PHASE_B1_PERMISSIONS = {
    "ADMINISTRATOR": [
        "sources.read",
        "sources.manage",
        "leads.read",
        "leads.analyze",
        "leads.review",
        "leads.handoff",
    ],
    "OPERATOR": ["sources.read", "sources.manage", "leads.read", "leads.analyze"],
    "REVIEWER": ["sources.read", "leads.read", "leads.review"],
    "READ_ONLY": ["sources.read", "leads.read"],
}


def refresh_phase_b1_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, permissions in PHASE_B1_PERMISSIONS.items():
        role = role_model.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(permission for permission in permissions if permission not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0010_phaseae2eownership")]

    operations = [
        migrations.RunPython(refresh_phase_b1_permissions, migrations.RunPython.noop)
    ]
