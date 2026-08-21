from django.db import migrations


MIXED_SELECT_EXPRESSIONS = {
    "knowledge_knowledgeconcept": (
        "organization_id = app_current_organization_id() OR "
        "(organization_id IS NULL AND scope = 'SYSTEM')"
    ),
    "knowledge_knowledgeevidence": (
        "organization_id = app_current_organization_id() OR organization_id IS NULL"
    ),
    "knowledge_knowledgealias": (
        "organization_id = app_current_organization_id() OR organization_id IS NULL"
    ),
    "knowledge_knowledgerelation": (
        "organization_id = app_current_organization_id() OR organization_id IS NULL"
    ),
}

ASSOCIATION_SELECT_EXPRESSIONS = {
    "knowledge_companyfactevidence": (
        "EXISTS (SELECT 1 FROM knowledge_companyfact parent "
        "WHERE parent.id = company_fact_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = evidence_id "
        "AND evidence.organization_id = app_current_organization_id())"
    ),
    "knowledge_icpproductlink": (
        "EXISTS (SELECT 1 FROM knowledge_icpprofile parent "
        "WHERE parent.id = icp_profile_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM catalog_product product "
        "WHERE product.id = product_id "
        "AND product.organization_id = app_current_organization_id())"
    ),
    "knowledge_websitepageproductlink": (
        "EXISTS (SELECT 1 FROM knowledge_websitepage parent "
        "WHERE parent.id = website_page_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM catalog_product product "
        "WHERE product.id = product_id "
        "AND product.organization_id = app_current_organization_id())"
    ),
    "knowledge_websitepageconceptlink": (
        "EXISTS (SELECT 1 FROM knowledge_websitepage parent "
        "WHERE parent.id = website_page_id "
        "AND parent.organization_id = app_current_organization_id()) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeconcept concept "
        "WHERE concept.id = concept_id AND ("
        "concept.organization_id = app_current_organization_id() OR "
        "(concept.organization_id IS NULL AND concept.scope = 'SYSTEM')))"
    ),
    "knowledge_knowledgeconcept_evidence": (
        "EXISTS (SELECT 1 FROM knowledge_knowledgeconcept parent "
        "WHERE parent.id = knowledgeconcept_id AND ("
        "parent.organization_id = app_current_organization_id() OR "
        "(parent.organization_id IS NULL AND parent.scope = 'SYSTEM'))) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))"
    ),
    "knowledge_knowledgerelation_evidence": (
        "EXISTS (SELECT 1 FROM knowledge_knowledgerelation parent "
        "WHERE parent.id = knowledgerelation_id AND ("
        "parent.organization_id = app_current_organization_id() OR "
        "parent.organization_id IS NULL)) "
        "AND EXISTS (SELECT 1 FROM knowledge_knowledgeevidence evidence "
        "WHERE evidence.id = knowledgeevidence_id AND ("
        "evidence.organization_id = app_current_organization_id() OR "
        "evidence.organization_id IS NULL))"
    ),
}


def _policy_name(table: str) -> str:
    return f"rls_{table.removeprefix('knowledge_')}_select"


def _replace_select_policies(schema_editor, *, require_context: bool) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return

    expressions = {**MIXED_SELECT_EXPRESSIONS, **ASSOCIATION_SELECT_EXPRESSIONS}
    for table, expression in expressions.items():
        policy_name = _policy_name(table)
        schema_editor.execute(f'DROP POLICY IF EXISTS "{policy_name}" ON "{table}"')
        if require_context:
            expression = (
                "app_current_organization_id() IS NOT NULL AND "
                f"({expression})"
            )
        schema_editor.execute(
            f'CREATE POLICY "{policy_name}" ON "{table}" '
            f"FOR SELECT USING ({expression})"
        )


def harden_select_policies(apps, schema_editor) -> None:
    _replace_select_policies(schema_editor, require_context=True)


def restore_select_policies(apps, schema_editor) -> None:
    _replace_select_policies(schema_editor, require_context=False)


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0007_enable_knowledge_tenant_rls"),
    ]

    operations = [
        migrations.RunPython(harden_select_policies, restore_select_policies),
    ]
