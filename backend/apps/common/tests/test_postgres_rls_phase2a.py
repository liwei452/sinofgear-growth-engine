import os
from contextlib import contextmanager
from importlib import import_module
from uuid import uuid4

import psycopg
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db import transaction
from psycopg.conninfo import conninfo_to_dict

from apps.ai.models import OrganizationAIProviderConfig, PromptVersion, ai_audit_writes
from apps.common.rls_manifest import RLS1_TABLES, RLS2A_TABLES
from apps.identity.models import Organization
from apps.jobs.models import Job
from apps.jobs.services import JobService


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="RLS acceptance requires PostgreSQL owner/runtime roles.",
    ),
]

GLOBAL_TABLES = {"ai_promptversion", "platforms_platform", "platforms_platformcapability"}
MIGRATIONS = tuple(
    import_module(name)
    for name in (
        "apps.ai.migrations.0008_enable_ai_tenant_rls",
        "apps.assets.migrations.0004_enable_assets_tenant_rls",
        "apps.audit.migrations.0004_enable_audit_tenant_rls",
        "apps.catalog.migrations.0004_enable_catalog_tenant_rls",
        "apps.jobs.migrations.0006_enable_jobs_tenant_rls",
        "apps.platforms.migrations.0012_enable_platforms_tenant_rls",
    )
)


def _runtime_parameters():
    try:
        parameters = conninfo_to_dict(os.environ["RLS_TEST_RUNTIME_DSN"])
    except KeyError:
        pytest.fail("RLS_TEST_RUNTIME_DSN is required for PostgreSQL RLS tests.")
    parameters["dbname"] = connection.settings_dict["NAME"]
    return parameters


@pytest.fixture
def runtime_connection():
    with psycopg.connect(**_runtime_parameters(), autocommit=True) as runtime:
        yield runtime


@pytest.fixture
def organizations():
    return (
        Organization.objects.create(name="RLS A", slug=f"rls-a-{uuid4().hex}"),
        Organization.objects.create(name="RLS B", slug=f"rls-b-{uuid4().hex}"),
    )


@pytest.fixture(autouse=True)
def system_prompt_contract():
    if PromptVersion.objects.filter(
        purpose="ASSET_UNDERSTAND", code="asset-understand-evidence-v1"
    ).exists():
        return
    seed = import_module("apps.ai.migrations.0007_asset_understanding_prompt_catalog")
    with ai_audit_writes():
        PromptVersion.objects.create(
            purpose=seed.PURPOSE,
            code=seed.PROMPT_CODE,
            provider="system",
            model="provider-agnostic",
            template=seed.TEMPLATE,
            output_schema=seed.OUTPUT_SCHEMA,
            version=1,
            status=PromptVersion.Status.PUBLISHED,
        )


@contextmanager
def _tenant(runtime, organization_id):
    runtime.execute("BEGIN")
    runtime.execute(
        "SELECT set_config('app.current_organization_id', %s, true)",
        (str(organization_id),),
    )
    try:
        yield
    finally:
        runtime.execute("ROLLBACK")


def test_phase2a_policy_shapes_and_runtime_role(runtime_connection):
    rows = runtime_connection.execute(
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY(%s)",
        (list(RLS1_TABLES | RLS2A_TABLES),),
    ).fetchall()
    assert {row[0] for row in rows} == RLS1_TABLES | RLS2A_TABLES
    assert all(row[1:] == (True, True) for row in rows)

    policies = runtime_connection.execute(
        "SELECT tablename, cmd FROM pg_policies WHERE schemaname = 'public' "
        "AND tablename = ANY(%s)",
        (list(RLS2A_TABLES),),
    ).fetchall()
    commands = {}
    for table, command in policies:
        commands.setdefault(table, []).append(command)
    assert all(sorted(commands[table]) == ["SELECT"] for table in GLOBAL_TABLES)
    direct = RLS2A_TABLES - GLOBAL_TABLES - {"jobs_jobattempt"}
    assert all(sorted(commands[table]) == ["ALL"] for table in direct)
    assert sorted(commands["jobs_jobattempt"]) == ["DELETE", "INSERT", "SELECT", "UPDATE"]
    assert runtime_connection.execute(
        "SELECT rolinherit, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone() == (False, False)
    assert runtime_connection.execute(
        "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
        "WHERE c.relname = ANY(%s) AND r.rolname = current_user",
        (list(RLS2A_TABLES),),
    ).fetchone() == (0,)


def test_runtime_cannot_record_migrations_or_mutate_frozen_snapshots(
    runtime_connection,
):
    assert runtime_connection.execute(
        "SELECT has_table_privilege(current_user, 'django_migrations', "
        "'INSERT,UPDATE,DELETE')"
    ).fetchone() == (False,)
    assert runtime_connection.execute(
        "SELECT has_table_privilege(current_user, "
        "'knowledge_knowledgecontextsnapshot', 'UPDATE,DELETE')"
    ).fetchone() == (False,)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "UPDATE knowledge_knowledgecontextsnapshot "
            "SET builder_version = builder_version WHERE false"
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "DELETE FROM knowledge_knowledgecontextsnapshot WHERE false"
        )

    class RuntimeMigrationConnection:
        vendor = "postgresql"

        @staticmethod
        def cursor():
            return runtime_connection.cursor()

    class RuntimeSchemaEditor:
        connection = RuntimeMigrationConnection()

    prompt_migration = import_module(
        "apps.ai.migrations.0007_asset_understanding_prompt_catalog"
    )
    prompt_count = PromptVersion.objects.count()
    with pytest.raises(RuntimeError, match="migration owner"):
        prompt_migration.seed_asset_understanding_prompt(None, RuntimeSchemaEditor())
    assert PromptVersion.objects.count() == prompt_count


def test_direct_and_global_tables_fail_closed_and_isolate_tenants(
    organizations, runtime_connection,
):
    organization_a, organization_b = organizations
    config_a = OrganizationAIProviderConfig.objects.create(organization=organization_a)
    config_b = OrganizationAIProviderConfig.objects.create(organization=organization_b)
    organization_c = Organization.objects.create(name="RLS C", slug=f"rls-c-{uuid4().hex}")
    prompt_id = PromptVersion.objects.filter(status=PromptVersion.Status.PUBLISHED).values_list(
        "id", flat=True
    ).first()
    assert runtime_connection.execute("SELECT count(*) FROM ai_organizationaiproviderconfig").fetchone() == (0,)
    assert runtime_connection.execute("SELECT count(*) FROM ai_promptversion").fetchone() == (0,)

    with _tenant(runtime_connection, organization_a.id):
        visible = runtime_connection.execute(
            "SELECT organization_id FROM ai_organizationaiproviderconfig"
        ).fetchall()
        assert visible == [(organization_a.id,)]
        assert runtime_connection.execute(
            "UPDATE ai_organizationaiproviderconfig SET model = 'blocked' WHERE id = %s",
            (config_b.id,),
        ).rowcount == 0
        assert runtime_connection.execute(
            "DELETE FROM ai_organizationaiproviderconfig WHERE id = %s", (config_b.id,)
        ).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime_connection.execute(
                "INSERT INTO ai_organizationaiproviderconfig "
                "(organization_id, provider, model, encrypted_api_key, enabled, "
                "daily_spent_micros, daily_reserved_micros, last_error_code, created_at, updated_at) "
                "VALUES (%s, 'deepseek', 'deepseek-chat', '', false, 0, 0, '', now(), now())",
                (organization_c.id,),
            )
        runtime_connection.execute("ROLLBACK")

    with _tenant(runtime_connection, organization_a.id):
        assert runtime_connection.execute(
            "SELECT count(*) FROM ai_promptversion WHERE id = %s", (prompt_id,)
        ).fetchone() == (1,)
        assert runtime_connection.execute(
            "UPDATE ai_promptversion SET provider = 'blocked' WHERE id = %s", (prompt_id,)
        ).rowcount == 0
        assert runtime_connection.execute(
            "DELETE FROM ai_promptversion WHERE id = %s", (prompt_id,)
        ).rowcount == 0
    with _tenant(runtime_connection, organization_a.id):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime_connection.execute(
                "INSERT INTO ai_promptversion "
                "(id, purpose, code, provider, model, template, output_schema, version, "
                "status, created_at) VALUES (%s, %s, 'blocked', 'system', "
                "'provider-agnostic', 'blocked', '{}', 1, 'PUBLISHED', now())",
                (uuid4(), f"BLOCKED_{uuid4().hex}"),
            )
        runtime_connection.execute("ROLLBACK")
    assert config_a.organization_id == organization_a.id


def test_job_attempt_policy_uses_the_locked_parent_organization(
    organizations, runtime_connection,
):
    organization_a, organization_b = organizations
    job_a = JobService.create(
        organization=organization_a,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={},
        idempotency_key=f"a-{uuid4()}",
    )
    job_b = JobService.create(
        organization=organization_b,
        job_type=Job.Type.CONTENT_GENERATE,
        input_snapshot={},
        idempotency_key=f"b-{uuid4()}",
    )
    JobService.claim(worker_id="rls-a", job_id=job_a.id)
    JobService.claim(worker_id="rls-b", job_id=job_b.id)

    with _tenant(runtime_connection, organization_a.id):
        assert runtime_connection.execute(
            "SELECT job_id FROM jobs_jobattempt"
        ).fetchall() == [(job_a.id,)]
        foreign_attempt = runtime_connection.execute(
            "SELECT id FROM jobs_jobattempt WHERE job_id = %s", (job_b.id,)
        ).fetchone()
        assert foreign_attempt is None


def test_transaction_local_tenant_is_cleared_after_commit_and_rollback(
    organizations, runtime_connection,
):
    organization, _ = organizations
    for terminator in ("COMMIT", "ROLLBACK"):
        runtime_connection.execute("BEGIN")
        runtime_connection.execute(
            "SELECT set_config('app.current_organization_id', %s, true)",
            (str(organization.id),),
        )
        runtime_connection.execute(terminator)
        assert runtime_connection.execute(
            "SELECT app_current_organization_id()"
        ).fetchone() == (None,)


def test_phase2a_migration_functions_round_trip_without_changing_prompt_data():
    prompt = PromptVersion.objects.filter(status=PromptVersion.Status.PUBLISHED).first()
    before = (prompt.id, prompt.template, prompt.output_schema)
    with connection.schema_editor() as schema_editor:
        for module in reversed(MIGRATIONS):
            module.disable_rls(None, schema_editor)
        for module in MIGRATIONS:
            module.enable_rls(None, schema_editor)
    prompt.refresh_from_db()
    assert (prompt.id, prompt.template, prompt.output_schema) == before


@pytest.mark.parametrize(
    ("table", "policy", "alteration"),
    [
        (
            "knowledge_companyfact",
            "rls_companyfact_all",
            "USING (true) WITH CHECK (true)",
        ),
        (
            "ai_organizationaiproviderconfig",
            "rls_ai_organizationaiproviderconfig_tenant_all",
            "USING (true) WITH CHECK (true)",
        ),
    ],
)
def test_database_audit_rejects_weakened_rls1_and_rls2a_policy_predicates(
    table, policy, alteration,
):
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f'ALTER POLICY "{policy}" ON "{table}" {alteration}')
        with pytest.raises(CommandError, match="policy contract mismatch"):
            call_command("audit_rls_coverage", database="default")
        transaction.set_rollback(True)
