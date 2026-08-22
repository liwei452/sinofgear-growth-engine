import hashlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


LATEST = ("growth", "0050_email_verification_pipeline")
PREVIOUS = ("growth", "0049_agent_context_provenance")


@pytest.mark.django_db(transaction=True)
def test_email_verification_migration_reverses_reapplies_and_restores_full_graph():
    from apps.growth.models import TargetAccount
    from apps.identity.models import Organization

    organization = Organization.objects.create(name="Migration", slug="email-migration")
    account = TargetAccount.objects.create(
        organization=organization,
        name="Preserved account",
        country="US",
    )
    executor = MigrationExecutor(connection)
    original_leaves = executor.loader.graph.leaf_nodes()
    assert LATEST in original_leaves
    reverse_targets = [target for target in original_leaves if target != LATEST]
    reverse_targets.append(PREVIOUS)

    try:
        executor.migrate(reverse_targets)
        old_apps = executor.loader.project_state(reverse_targets).apps
        old_account = old_apps.get_model("growth", "TargetAccount")
        assert old_account.objects.filter(pk=account.id).exists()
        with pytest.raises(LookupError):
            old_apps.get_model("growth", "EmailVerificationRun")

        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(latest)
        current_apps = executor.loader.project_state(latest).apps
        run_model = current_apps.get_model("growth", "EmailVerificationRun")
        email = "migration@example.com"
        run = run_model.objects.create(
            organization_id=organization.id,
            normalized_email=email,
            email_fingerprint=hashlib.sha256(email.encode()).hexdigest(),
            domain="example.com",
            idempotency_key="migration-roundtrip",
        )
        assert run_model.objects.filter(pk=run.id).exists()
        assert current_apps.get_model("growth", "TargetAccount").objects.filter(
            pk=account.id
        ).exists()
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
