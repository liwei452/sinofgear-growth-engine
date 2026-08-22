from importlib import import_module

from apps.common.management.commands.audit_rls_coverage import (
    _expected_policy_contracts,
)
from apps.common.rls_manifest import (
    EARLY_RLS_TABLES,
    RLSCategory,
    RLSPhase,
    RLS_MANIFEST,
)


TABLES = {
    "growth_emailverificationrun",
    "growth_emailverificationevidence",
}


def test_manifest_and_migration_freeze_the_same_early_rls_tables():
    migration = import_module("apps.growth.migrations.0050_email_verification_pipeline")
    entries = {entry.db_table: entry for entry in RLS_MANIFEST if entry.db_table in TABLES}

    assert set(entries) == EARLY_RLS_TABLES == TABLES
    assert set(migration.RLS_TABLES) == TABLES
    assert all(entry.category == RLSCategory.TENANT_DIRECT for entry in entries.values())
    assert all(entry.phase == RLSPhase.RLS_2C for entry in entries.values())
    assert all(entry.contains_customer_content for entry in entries.values())
    assert all(entry.background_task_access for entry in entries.values())


def test_audit_contract_has_mutable_run_and_append_only_evidence_policies():
    contracts = _expected_policy_contracts()

    run_commands = {
        command
        for (table, _), (command, _, _) in contracts.items()
        if table == "growth_emailverificationrun"
    }
    evidence_commands = {
        command
        for (table, _), (command, _, _) in contracts.items()
        if table == "growth_emailverificationevidence"
    }
    assert run_commands == {"SELECT", "INSERT", "UPDATE"}
    assert evidence_commands == {"SELECT", "INSERT"}
