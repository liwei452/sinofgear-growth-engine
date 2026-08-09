from django.db import migrations


CAMPAIGN_PERMISSIONS = {
    "ADMINISTRATOR": ("Administrator", ["campaigns.read", "campaigns.manage", "campaigns.review"]),
    "OPERATOR": ("Operator", ["campaigns.read", "campaigns.manage"]),
    "REVIEWER": ("Reviewer", ["campaigns.read", "campaigns.review"]),
    "READ_ONLY": ("Read only", ["campaigns.read"]),
}


def refresh_builtin_role_permissions(apps, schema_editor) -> None:
    role_model = apps.get_model("identity", "Role")
    for code, (name, campaign_permissions) in CAMPAIGN_PERMISSIONS.items():
        role, created = role_model.objects.get_or_create(
            code=code,
            defaults={"name": name, "permissions": campaign_permissions},
        )
        if created:
            continue
        merged = list(role.permissions)
        merged.extend(
            permission
            for permission in campaign_permissions
            if permission not in merged
        )
        if merged != role.permissions:
            role.permissions = merged
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0004_refresh_asset_permissions")]
    operations = [
        migrations.RunPython(
            refresh_builtin_role_permissions,
            reverse_code=migrations.RunPython.noop,
        )
    ]
