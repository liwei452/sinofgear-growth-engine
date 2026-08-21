import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ProviderBackfillMigrationTest(TransactionTestCase):
    migrate_from = [
        ("platforms", "0008_socialaccount_connection_state_and_more"),
        ("identity", "0010_phaseae2eownership"),
    ]
    migrate_to = [("platforms", "0010_remove_socialaccount_platforms_social_account_provider_shape_and_more")]

    def tearDown(self):
        MigrationExecutor(connection).migrate([("platforms", "0012_enable_platforms_tenant_rls")])
        super().tearDown()

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        Organization = old_apps.get_model("identity", "Organization")
        Platform = old_apps.get_model("platforms", "Platform")
        ConnectorCredential = old_apps.get_model("platforms", "ConnectorCredential")
        SocialAccount = old_apps.get_model("platforms", "SocialAccount")

        self.organization = Organization.objects.create(
            name="Migration Org", slug=f"migration-{uuid.uuid4().hex[:10]}"
        )
        self.platform = Platform.objects.create(
            code=f"PLAT-{uuid.uuid4().hex[:10]}", name="Migration Platform"
        )
        self.credential = ConnectorCredential.objects.create(
            organization=self.organization,
            platform=self.platform,
            secret_reference="vault://fixture",
            granted_scopes=["PUBLISH"],
        )
        self.account = SocialAccount.objects.create(
            organization=self.organization,
            platform=self.platform,
            credential=self.credential,
            external_id="page-1",
            display_name="LinkedIn Page",
            publish_mode="API_AUTO",
            connector_metadata={"connection_kind": "official_oauth"},
        )
        self.account_pk = self.account.pk
        self.credential_pk = self.credential.pk

    def test_migration_backfills_old_accounts_as_direct(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps

        SocialAccount = new_apps.get_model("platforms", "SocialAccount")
        account = SocialAccount.objects.get(pk=self.account_pk)

        assert account.pk == self.account_pk
        assert account.credential_id == self.credential_pk
        assert account.external_id == "page-1"
        assert account.connector_metadata == {"connection_kind": "official_oauth"}
        assert account.provider == "DIRECT"
        assert account.provider_connection_id is None
        assert account.provider_account_id == ""
