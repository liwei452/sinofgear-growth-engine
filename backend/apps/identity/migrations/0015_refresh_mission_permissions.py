from django.db import migrations


NEW_PERMISSIONS = {
    "ADMINISTRATOR": [
        "missions.read",
        "missions.manage",
        "missions.review",
    ],
    "OPERATOR": [
        "missions.read",
    ],
    "REVIEWER": [
        "missions.read",
    ],
    "READ_ONLY": [
        "missions.read",
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
    dependencies = [("identity", "0014_organization_ai_daily_reserved_on_and_more")]

    operations = [
        migrations.RunPython(refresh_permissions, migrations.RunPython.noop),
    ]
