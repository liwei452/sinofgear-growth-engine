from django.db import migrations


DIRECT_TABLES = ("ai_airun", "ai_organizationaiproviderconfig")
GLOBAL_READ_TABLES = ("ai_promptversion",)


def _policy(table, suffix):
    return f"rls_{table}_{suffix}"


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in DIRECT_TABLES:
        expression = "organization_id = app_current_organization_id()"
        schema_editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        schema_editor.execute(
            f'CREATE POLICY "{_policy(table, "tenant_all")}" ON "{table}" '
            f"FOR ALL USING ({expression}) WITH CHECK ({expression})"
        )
    for table in GLOBAL_READ_TABLES:
        schema_editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        schema_editor.execute(
            f'CREATE POLICY "{_policy(table, "context_select")}" ON "{table}" '
            "FOR SELECT USING (app_current_organization_id() IS NOT NULL)"
        )


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in DIRECT_TABLES:
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "{_policy(table, "tenant_all")}" ON "{table}"'
        )
    for table in GLOBAL_READ_TABLES:
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "{_policy(table, "context_select")}" ON "{table}"'
        )
    for table in (*DIRECT_TABLES, *GLOBAL_READ_TABLES):
        schema_editor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0007_asset_understanding_prompt_catalog"),
        ("knowledge", "0008_harden_knowledge_rls_context"),
    ]
    operations = [migrations.RunPython(enable_rls, disable_rls)]
