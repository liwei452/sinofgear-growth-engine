from django.db import migrations


PUBLISHING_PERMISSIONS = {
    "ADMINISTRATOR": ["publishing.read", "publishing.manage"],
    "OPERATOR": ["publishing.read", "publishing.manage"],
    "REVIEWER": ["publishing.read"],
    "READ_ONLY": ["publishing.read"],
}


def refresh_publishing_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, permissions in PUBLISHING_PERMISSIONS.items():
        role = role_model.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(item for item in permissions if item not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0007_refresh_content_permissions")]
    operations = [
        migrations.RunPython(
            refresh_publishing_permissions, migrations.RunPython.noop
        )
    ]
