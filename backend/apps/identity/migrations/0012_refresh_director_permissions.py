from django.db import migrations


DIRECTOR_PERMISSIONS = {
    "ADMINISTRATOR": ["director.read", "director.decide"],
    "OPERATOR": ["director.read", "director.decide"],
    "REVIEWER": ["director.read", "director.decide"],
    "READ_ONLY": ["director.read"],
}


def refresh_director_permissions(apps, schema_editor):
    role_model = apps.get_model("identity", "Role")
    for code, permissions in DIRECTOR_PERMISSIONS.items():
        role = role_model.objects.filter(code=code).first()
        if role is None:
            continue
        merged = list(role.permissions)
        merged.extend(permission for permission in permissions if permission not in merged)
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0011_refresh_phase_b1_permissions")]

    operations = [
        migrations.RunPython(refresh_director_permissions, migrations.RunPython.noop)
    ]
