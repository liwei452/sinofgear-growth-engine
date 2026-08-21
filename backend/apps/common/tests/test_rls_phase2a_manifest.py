from importlib import import_module

from apps.common.rls_manifest import RLS2A_TABLES, RLSCategory, RLSPhase, RLS_MANIFEST


MIGRATIONS = (
    "apps.ai.migrations.0008_enable_ai_tenant_rls",
    "apps.assets.migrations.0004_enable_assets_tenant_rls",
    "apps.audit.migrations.0004_enable_audit_tenant_rls",
    "apps.catalog.migrations.0004_enable_catalog_tenant_rls",
    "apps.jobs.migrations.0006_enable_jobs_tenant_rls",
    "apps.platforms.migrations.0012_enable_platforms_tenant_rls",
)


def _migration_tables():
    tables = set()
    for module_name in MIGRATIONS:
        module = import_module(module_name)
        tables.update(getattr(module, "DIRECT_TABLES", ()))
        tables.update(getattr(module, "GLOBAL_READ_TABLES", ()))
        if module_name.startswith("apps.jobs"):
            tables.update({"jobs_job", "jobs_jobattempt"})
    return tables


def test_phase2a_migrations_freeze_exactly_the_manifest_table_set():
    manifest_tables = {
        entry.db_table for entry in RLS_MANIFEST if entry.phase == RLSPhase.RLS_2A
    }
    assert _migration_tables() == RLS2A_TABLES == manifest_tables


def test_phase2a_manifest_categories_match_the_policy_groups():
    entries = {
        entry.db_table: entry for entry in RLS_MANIFEST if entry.phase == RLSPhase.RLS_2A
    }
    globals_ = {"ai_promptversion", "platforms_platform", "platforms_platformcapability"}
    assert {table for table, entry in entries.items() if entry.category == RLSCategory.GLOBAL_CONTEXT_READ} == globals_
    assert entries["jobs_jobattempt"].category == RLSCategory.TENANT_PARENT
    assert all(
        entry.category == RLSCategory.TENANT_DIRECT
        for table, entry in entries.items()
        if table not in globals_ | {"jobs_jobattempt"}
    )
