from django.db import migrations


BUILTIN_ROLES = {
    "ADMINISTRATOR": (
        "Administrator",
        [
            "memberships.read",
            "memberships.manage",
            "credentials.manage",
            "knowledge.read",
            "knowledge.create",
            "knowledge.review_organization",
            "knowledge.manage_system",
            "knowledge.deprecate",
        ],
    ),
    "OPERATOR": (
        "Operator",
        [
            "memberships.read",
            "memberships.manage",
            "knowledge.read",
            "knowledge.create",
        ],
    ),
    "REVIEWER": (
        "Reviewer",
        [
            "memberships.read",
            "knowledge.read",
            "knowledge.review_organization",
        ],
    ),
    "READ_ONLY": (
        "Read only",
        ["memberships.read", "knowledge.read"],
    ),
}


def refresh_builtin_role_permissions(apps, schema_editor) -> None:
    role_model = apps.get_model("identity", "Role")
    for code, (name, permissions) in BUILTIN_ROLES.items():
        role_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "permissions": permissions},
        )


class Migration(migrations.Migration):
    dependencies = [("identity", "0001_initial")]

    operations = [
        migrations.RunPython(
            refresh_builtin_role_permissions,
            reverse_code=migrations.RunPython.noop,
        )
    ]
