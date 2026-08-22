from django.db import migrations


DIRECT_TABLES = (
    "platforms_accountconnectionsession",
    "platforms_connectorcredential",
    "platforms_encryptedoauthcredential",
    "platforms_oauthconnectionattempt",
    "platforms_providerconnection",
    "platforms_providerconnectionevent",
    "platforms_socialaccount",
)
GLOBAL_READ_TABLES = ("platforms_platform", "platforms_platformcapability")


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    expression = "organization_id = app_current_organization_id()"
    for table in DIRECT_TABLES:
        policy = f"rls_{table}_tenant_all"
        schema_editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        schema_editor.execute(
            f'CREATE POLICY "{policy}" ON "{table}" FOR ALL '
            f"USING ({expression}) WITH CHECK ({expression})"
        )
    for table in GLOBAL_READ_TABLES:
        policy = f"rls_{table}_context_select"
        schema_editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        schema_editor.execute(
            f'CREATE POLICY "{policy}" ON "{table}" FOR SELECT '
            "USING (app_current_organization_id() IS NOT NULL)"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in DIRECT_TABLES:
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "rls_{table}_tenant_all" ON "{table}"'
        )
    for table in GLOBAL_READ_TABLES:
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "rls_{table}_context_select" ON "{table}"'
        )
    for table in (*DIRECT_TABLES, *GLOBAL_READ_TABLES):
        schema_editor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("platforms", "0011_providerconnectionevent"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]
    operations = [migrations.RunPython(enable_rls, disable_rls)]
