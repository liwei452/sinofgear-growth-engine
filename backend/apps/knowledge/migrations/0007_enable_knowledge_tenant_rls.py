from django.db import migrations


RUNTIME_ROLE = "sinofgear_app"

DIRECT_TABLES = (
    "knowledge_companyknowledgeprofile",
    "knowledge_companyfact",
    "knowledge_icpprofile",
    "knowledge_websitepage",
    "knowledge_knowledgecontextsnapshot",
)

MIXED_TABLES = {
    "knowledge_knowledgeconcept": "organization_id IS NULL AND scope = 'SYSTEM'",
    "knowledge_knowledgeevidence": "organization_id IS NULL",
    "knowledge_knowledgealias": "organization_id IS NULL",
    "knowledge_knowledgerelation": "organization_id IS NULL",
}

ASSOCIATION_TABLES = {
    "knowledge_companyfactevidence": (
        "EXISTS (SELECT 1 FROM knowledge_companyfact parent "
        "WHERE parent.id = company_fact_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = evidence_id "
        "AND evidence.organization_id = app_current_organization_id())",
        None,
    ),
    "knowledge_icpproductlink": (
        "EXISTS (SELECT 1 FROM knowledge_icpprofile parent "
        "WHERE parent.id = icp_profile_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM catalog_product product "
        "WHERE product.id = product_id "
        "AND product.organization_id = app_current_organization_id())",
        None,
    ),
    "knowledge_websitepageproductlink": (
        "EXISTS (SELECT 1 FROM knowledge_websitepage parent "
        "WHERE parent.id = website_page_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM catalog_product product "
        "WHERE product.id = product_id "
        "AND product.organization_id = app_current_organization_id())",
        None,
    ),
    "knowledge_websitepageconceptlink": (
        "EXISTS (SELECT 1 FROM knowledge_websitepage parent "
        "WHERE parent.id = website_page_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeconcept concept "
        "WHERE concept.id = concept_id AND ("
        "concept.organization_id = app_current_organization_id() OR "
        "(concept.organization_id IS NULL AND concept.scope = 'SYSTEM')))",
        None,
    ),
    "knowledge_knowledgeconcept_evidence": (
        "EXISTS (SELECT 1 FROM knowledge_knowledgeconcept parent "
        "WHERE parent.id = knowledgeconcept_id AND ("
        "parent.organization_id = app_current_organization_id() OR "
        "(parent.organization_id IS NULL AND parent.scope = 'SYSTEM'))) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))",
        "EXISTS (SELECT 1 FROM knowledge_knowledgeconcept parent "
        "WHERE parent.id = knowledgeconcept_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))",
    ),
    "knowledge_knowledgerelation_evidence": (
        "EXISTS (SELECT 1 FROM knowledge_knowledgerelation parent "
        "WHERE parent.id = knowledgerelation_id AND ("
        "parent.organization_id = app_current_organization_id() OR "
        "parent.organization_id IS NULL)) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))",
        "EXISTS (SELECT 1 FROM knowledge_knowledgerelation parent "
        "WHERE parent.id = knowledgerelation_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))",
    ),
}


def _policy_name(table: str, operation: str) -> str:
    short_table = table.removeprefix("knowledge_")
    return f"rls_{short_table}_{operation.lower()}"


def _enable_rls(schema_editor, table: str) -> None:
    schema_editor.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def enable_knowledge_rls(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION app_current_organization_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        SET search_path = pg_catalog
        AS $$
            SELECT NULLIF(current_setting('app.current_organization_id', true), '')::uuid
        $$
        """
    )
    schema_editor.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RUNTIME_ROLE}') THEN
                REVOKE ALL ON FUNCTION app_current_organization_id() FROM PUBLIC;
                GRANT EXECUTE ON FUNCTION app_current_organization_id() TO {RUNTIME_ROLE};
            END IF;
        END
        $$
        """
    )

    for table in DIRECT_TABLES:
        _enable_rls(schema_editor, table)
        expression = "organization_id = app_current_organization_id()"
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "all")}" ON "{table}" '
            f"FOR ALL USING ({expression}) WITH CHECK ({expression})"
        )

    for table, system_expression in MIXED_TABLES.items():
        _enable_rls(schema_editor, table)
        tenant_expression = "organization_id = app_current_organization_id()"
        read_expression = f"{tenant_expression} OR ({system_expression})"
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "select")}" ON "{table}" '
            f"FOR SELECT USING ({read_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "insert")}" ON "{table}" '
            f"FOR INSERT WITH CHECK ({tenant_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "update")}" ON "{table}" '
            f"FOR UPDATE USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "delete")}" ON "{table}" '
            f"FOR DELETE USING ({tenant_expression})"
        )

    for table, (read_expression, write_expression) in ASSOCIATION_TABLES.items():
        _enable_rls(schema_editor, table)
        write_expression = write_expression or read_expression
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "select")}" ON "{table}" '
            f"FOR SELECT USING ({read_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "insert")}" ON "{table}" '
            f"FOR INSERT WITH CHECK ({write_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "update")}" ON "{table}" '
            f"FOR UPDATE USING ({write_expression}) WITH CHECK ({write_expression})"
        )
        schema_editor.execute(
            f'CREATE POLICY "{_policy_name(table, "delete")}" ON "{table}" '
            f"FOR DELETE USING ({write_expression})"
        )


def disable_knowledge_rls(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return

    for table in ASSOCIATION_TABLES:
        for operation in ("select", "insert", "update", "delete"):
            schema_editor.execute(
                f'DROP POLICY IF EXISTS "{_policy_name(table, operation)}" ON "{table}"'
            )
    for table in MIXED_TABLES:
        for operation in ("select", "insert", "update", "delete"):
            schema_editor.execute(
                f'DROP POLICY IF EXISTS "{_policy_name(table, operation)}" ON "{table}"'
            )
    for table in DIRECT_TABLES:
        schema_editor.execute(
            f'DROP POLICY IF EXISTS "{_policy_name(table, "all")}" ON "{table}"'
        )
    for table in (*DIRECT_TABLES, *MIXED_TABLES, *ASSOCIATION_TABLES):
        schema_editor.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    schema_editor.execute("DROP FUNCTION IF EXISTS app_current_organization_id()")


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0006_knowledge_context_snapshot"),
    ]

    operations = [
        migrations.RunPython(enable_knowledge_rls, disable_knowledge_rls),
    ]
