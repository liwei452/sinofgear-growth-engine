from django.db import migrations


JOB_PERMISSIONS = {
    "ADMINISTRATOR": ("Administrator", ["jobs.read", "jobs.manage"]),
    "OPERATOR": ("Operator", ["jobs.read", "jobs.manage"]),
    "REVIEWER": ("Reviewer", ["jobs.read"]),
    "READ_ONLY": ("Read only", ["jobs.read"]),
}


def refresh_job_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, (name, permissions) in JOB_PERMISSIONS.items():
        role, created = role_model.objects.get_or_create(
            code=code, defaults={"name": name, "permissions": permissions}
        )
        if created:
            continue
        merged = list(role.permissions)
        merged.extend(item for item in permissions if item not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0005_refresh_campaign_permissions")]
    operations = [
        migrations.RunPython(
            refresh_job_permissions, reverse_code=migrations.RunPython.noop
        )
    ]
