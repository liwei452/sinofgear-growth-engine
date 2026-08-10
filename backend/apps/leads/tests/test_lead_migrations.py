from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_analysis_lease_migration_repairs_legacy_rows_before_exact_constraint():
    before = ("leads", "0005_alter_leadcandidate_options_and_more")
    after = (
        "leads",
        "0006_remove_leadcandidate_leads_candidate_lease_status_valid_and_more",
    )
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()

    try:
        executor.migrate([before])
        old_apps = executor.loader.project_state([before]).apps
        organization_model = old_apps.get_model("identity", "Organization")
        candidate_model = old_apps.get_model("leads", "LeadCandidate")
        organization = organization_model.objects.create(
            name="Lease migration",
            slug="lease-migration",
        )
        orphan = candidate_model.objects.create(
            organization=organization,
            status="ANALYZING",
            analysis_lease_token=None,
        )
        active_lease = uuid4()
        active = candidate_model.objects.create(
            organization=organization,
            status="ANALYZED",
            analysis_lease_token=active_lease,
        )
        analyzed = candidate_model.objects.create(
            organization=organization,
            status="ANALYZED",
            analysis_lease_token=None,
        )

        executor = MigrationExecutor(connection)
        executor.migrate([after])
        migrated_model = executor.loader.project_state([after]).apps.get_model(
            "leads", "LeadCandidate"
        )

        migrated_orphan = migrated_model.objects.get(pk=orphan.pk)
        migrated_active = migrated_model.objects.get(pk=active.pk)
        migrated_analyzed = migrated_model.objects.get(pk=analyzed.pk)
        assert (
            migrated_orphan.status,
            migrated_orphan.analysis_lease_token,
        ) == ("DISCOVERED", None)
        assert (
            migrated_active.status,
            migrated_active.analysis_lease_token,
        ) == ("ANALYZING", active_lease)
        assert (
            migrated_analyzed.status,
            migrated_analyzed.analysis_lease_token,
        ) == ("ANALYZED", None)
    finally:
        MigrationExecutor(connection).migrate(latest)
