from dataclasses import replace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.common import rls_manifest
from apps.common.rls_manifest import (
    RLS_MANIFEST,
    RLSCategory,
    RLSManifestError,
    assert_rls_coverage,
    iter_business_models,
)


def test_all_managed_business_tables_are_classified_once():
    assert_rls_coverage()

    discovered = {
        (model._meta.label, model._meta.db_table) for model in iter_business_models()
    }
    classified = {(entry.model_label, entry.db_table) for entry in RLS_MANIFEST}
    assert classified == discovered


def test_duplicate_manifest_classification_is_rejected():
    duplicate_entries = (*RLS_MANIFEST, RLS_MANIFEST[0])

    with pytest.raises(RLSManifestError, match="duplicate"):
        assert_rls_coverage(entries=duplicate_entries)


@pytest.mark.parametrize("invalid_kind", ["table", "parent_path"])
def test_invalid_table_or_parent_path_is_rejected(invalid_kind):
    if invalid_kind == "table":
        original = RLS_MANIFEST[0]
        invalid = replace(original, db_table="missing_business_table")
    else:
        original = next(
            entry
            for entry in RLS_MANIFEST
            if entry.category == RLSCategory.TENANT_PARENT
        )
        invalid = replace(original, parent_paths=("missing_parent.organization",))
    entries = tuple(invalid if entry is original else entry for entry in RLS_MANIFEST)

    with pytest.raises(RLSManifestError, match="missing_business_table|missing_parent"):
        assert_rls_coverage(entries=entries)


def test_audit_command_fails_for_an_intentionally_unclassified_model(monkeypatch):
    incomplete = tuple(
        entry for entry in RLS_MANIFEST if entry.model_label != "catalog.Product"
    )
    monkeypatch.setattr(rls_manifest, "RLS_MANIFEST", incomplete)

    with pytest.raises(CommandError, match=r"catalog\.Product.*catalog_product"):
        call_command("audit_rls_coverage")
