from django.db import migrations


TRACKING_PERMISSIONS = {
    "ADMINISTRATOR": ["tracking.read", "tracking.manage"],
    "OPERATOR": ["tracking.read", "tracking.manage"],
    "REVIEWER": ["tracking.read"],
    "READ_ONLY": ["tracking.read"],
}


def refresh_tracking_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, permissions in TRACKING_PERMISSIONS.items():
        role = role_model.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(permission for permission in permissions if permission not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0008_refresh_publishing_permissions")]
    operations = [
        migrations.RunPython(refresh_tracking_permissions, migrations.RunPython.noop)
    ]
