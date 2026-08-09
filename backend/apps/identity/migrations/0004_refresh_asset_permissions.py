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
            "products.read",
            "products.manage",
            "assets.read",
            "assets.manage",
        ],
    ),
    "OPERATOR": (
        "Operator",
        [
            "memberships.read",
            "memberships.manage",
            "knowledge.read",
            "knowledge.create",
            "products.read",
            "products.manage",
            "assets.read",
            "assets.manage",
        ],
    ),
    "REVIEWER": (
        "Reviewer",
        [
            "memberships.read",
            "knowledge.read",
            "knowledge.review_organization",
            "products.read",
            "assets.read",
        ],
    ),
    "READ_ONLY": (
        "Read only",
        ["memberships.read", "knowledge.read", "products.read", "assets.read"],
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
    dependencies = [("identity", "0003_refresh_product_permissions")]

    operations = [
        migrations.RunPython(
            refresh_builtin_role_permissions,
            reverse_code=migrations.RunPython.noop,
        )
    ]
