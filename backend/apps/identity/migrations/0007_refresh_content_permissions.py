from django.db import migrations


CONTENT_PERMISSIONS = {
    "ADMINISTRATOR": ["content.read", "content.manage", "content.review"],
    "OPERATOR": ["content.read", "content.manage"],
    "REVIEWER": ["content.read", "content.review"],
    "READ_ONLY": ["content.read"],
}


def refresh_content_permissions(apps, schema_editor):
    Role = apps.get_model("identity", "Role")
    for code, permissions in CONTENT_PERMISSIONS.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(item for item in permissions if item not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0006_refresh_job_permissions")]
    operations = [migrations.RunPython(refresh_content_permissions, migrations.RunPython.noop)]
