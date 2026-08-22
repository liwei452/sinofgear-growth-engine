from collections import Counter
from importlib import import_module
import re

from django.db import connections
from django.core.management.base import BaseCommand, CommandError

from apps.common.rls_manifest import (
    RLS_MANIFEST,
    RLS1_TABLES,
    RLS2A_TABLES,
    RLSManifestError,
    RLSPhase,
    assert_rls_coverage,
)


class Command(BaseCommand):
    help = "Validate that every managed concrete business table has one RLS classification."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--database",
            nargs="?",
            const="default",
            default=None,
            help="Also validate installed PostgreSQL RLS policies (optional alias).",
        )

    def handle(self, *args, **options) -> None:
        del args
        try:
            assert_rls_coverage()
        except RLSManifestError as error:
            raise CommandError(f"RLS coverage audit failed:\n{error}") from error

        if alias := options["database"]:
            self._audit_database(alias)

        phase_counts = Counter(entry.phase for entry in RLS_MANIFEST)
        summary = " ".join(f"{phase.value}={phase_counts[phase]}" for phase in RLSPhase)
        self.stdout.write(
            self.style.SUCCESS(
                f"RLS coverage manifest valid: tables={len(RLS_MANIFEST)} {summary}"
            )
        )

    @staticmethod
    def _audit_database(alias: str) -> None:
        connection = connections[alias]
        if connection.vendor != "postgresql":
            raise CommandError("Database RLS audit requires PostgreSQL.")

        expected = RLS1_TABLES | RLS2A_TABLES
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = ANY(%s)",
                [list(expected)],
            )
            shapes = {name: (enabled, forced) for name, enabled, forced in cursor.fetchall()}
            cursor.execute(
                "SELECT tablename, policyname, roles, cmd, qual, with_check "
                "FROM pg_policies WHERE schemaname = 'public' "
                "AND tablename = ANY(%s)",
                [list(expected)],
            )
            policies = {
                (table, name): (tuple(roles), command, qual, with_check)
                for table, name, roles, command, qual, with_check in cursor.fetchall()
            }
            cursor.execute(
                "SELECT rolname, rolinherit, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('sinofgear_owner', 'sinofgear_app')"
            )
            roles = {name: (inherit, bypass) for name, inherit, bypass in cursor.fetchall()}
            cursor.execute(
                "SELECT count(*) FROM pg_class table_object "
                "JOIN pg_roles owner ON owner.oid = table_object.relowner "
                "WHERE table_object.relname = ANY(%s) AND owner.rolname = 'sinofgear_app'",
                [list(expected)],
            )
            runtime_owned = cursor.fetchone()[0]
            cursor.execute(
                "SELECT has_function_privilege('sinofgear_app', "
                "'app_current_organization_id()', 'EXECUTE')"
            )
            helper_executable = cursor.fetchone()[0]
            cursor.execute(
                "SELECT pg_has_role('sinofgear_app', 'sinofgear_owner', 'MEMBER')"
            )
            runtime_inherits_owner = cursor.fetchone()[0]
            cursor.execute(
                "SELECT "
                "has_table_privilege('sinofgear_app', 'django_migrations', 'SELECT'), "
                "has_table_privilege('sinofgear_app', 'django_migrations', "
                "'INSERT,UPDATE,DELETE'), "
                "has_table_privilege('sinofgear_app', "
                "'knowledge_knowledgecontextsnapshot', 'SELECT,INSERT'), "
                "has_table_privilege('sinofgear_app', "
                "'knowledge_knowledgecontextsnapshot', 'UPDATE,DELETE')"
            )
            runtime_privileges = cursor.fetchone()

        errors = []
        missing = expected - shapes.keys()
        if missing:
            errors.append(f"database tables missing from RLS audit: {', '.join(sorted(missing))}")
        invalid = sorted(table for table, shape in shapes.items() if shape != (True, True))
        if invalid:
            errors.append(f"RLS is not enabled and forced: {', '.join(invalid)}")
        contracts = _expected_policy_contracts()
        if policies.keys() != contracts.keys():
            missing_policies = contracts.keys() - policies.keys()
            unexpected_policies = policies.keys() - contracts.keys()
            if missing_policies:
                errors.append(
                    "missing policies: "
                    + ", ".join(f"{table}.{name}" for table, name in sorted(missing_policies))
                )
            if unexpected_policies:
                errors.append(
                    "unexpected policies: "
                    + ", ".join(
                        f"{table}.{name}" for table, name in sorted(unexpected_policies)
                    )
                )
        for key in sorted(contracts.keys() & policies.keys()):
            actual_roles, actual_command, actual_using, actual_check = policies[key]
            expected_command, expected_using, expected_check = contracts[key]
            if (
                actual_roles != ("public",)
                or actual_command != expected_command
                or _normalize_policy_expression(actual_using)
                != _normalize_policy_expression(expected_using)
                or _normalize_policy_expression(actual_check)
                != _normalize_policy_expression(expected_check)
            ):
                errors.append(
                    f"{key[0]}.{key[1]}: policy contract mismatch"
                )
        if roles.get("sinofgear_app") != (False, False):
            errors.append("sinofgear_app must be NOINHERIT and NOBYPASSRLS")
        if roles.get("sinofgear_owner") is None:
            errors.append("sinofgear_owner role is missing")
        if runtime_owned:
            errors.append("sinofgear_app owns one or more protected RLS tables")
        if runtime_inherits_owner:
            errors.append("sinofgear_app can SET ROLE to sinofgear_owner")
        if not helper_executable:
            errors.append("sinofgear_app cannot execute app_current_organization_id()")
        if runtime_privileges != (True, False, True, False):
            errors.append(
                "sinofgear_app migration-recorder or frozen-Snapshot privileges are unsafe"
            )
        if errors:
            raise CommandError("Database RLS audit failed:\n" + "\n".join(errors))


def _normalize_policy_expression(expression: str | None) -> str | None:
    if expression is None:
        return None
    normalized = expression.lower().replace("::text", "")
    for table in RLS1_TABLES | RLS2A_TABLES:
        normalized = normalized.replace(f"{table}.", "")
    return re.sub(r"[\s()]", "", normalized)


def _expected_policy_contracts():
    contracts = {}
    tenant = "organization_id = app_current_organization_id()"
    knowledge_7 = import_module(
        "apps.knowledge.migrations.0007_enable_knowledge_tenant_rls"
    )
    knowledge_8 = import_module(
        "apps.knowledge.migrations.0008_harden_knowledge_rls_context"
    )
    for table in knowledge_7.DIRECT_TABLES:
        contracts[(table, knowledge_7._policy_name(table, "all"))] = (
            "ALL", tenant, tenant,
        )
    for table in knowledge_7.MIXED_TABLES:
        read = (
            "app_current_organization_id() IS NOT NULL AND ("
            f"{knowledge_8.MIXED_SELECT_EXPRESSIONS[table]})"
        )
        prefix = table.removeprefix("knowledge_")
        contracts[(table, f"rls_{prefix}_select")] = ("SELECT", read, None)
        contracts[(table, f"rls_{prefix}_insert")] = ("INSERT", None, tenant)
        contracts[(table, f"rls_{prefix}_update")] = ("UPDATE", tenant, tenant)
        contracts[(table, f"rls_{prefix}_delete")] = ("DELETE", tenant, None)
    for table, (read_7, write) in knowledge_7.ASSOCIATION_TABLES.items():
        read = (
            "app_current_organization_id() IS NOT NULL AND ("
            f"{knowledge_8.ASSOCIATION_SELECT_EXPRESSIONS[table]})"
        )
        write = write or read_7
        prefix = table.removeprefix("knowledge_")
        contracts[(table, f"rls_{prefix}_select")] = ("SELECT", read, None)
        contracts[(table, f"rls_{prefix}_insert")] = ("INSERT", None, write)
        contracts[(table, f"rls_{prefix}_update")] = ("UPDATE", write, write)
        contracts[(table, f"rls_{prefix}_delete")] = ("DELETE", write, None)

    direct_modules = (
        "apps.ai.migrations.0008_enable_ai_tenant_rls",
        "apps.assets.migrations.0004_enable_assets_tenant_rls",
        "apps.audit.migrations.0004_enable_audit_tenant_rls",
        "apps.catalog.migrations.0004_enable_catalog_tenant_rls",
        "apps.platforms.migrations.0012_enable_platforms_tenant_rls",
    )
    for module_name in direct_modules:
        module = import_module(module_name)
        for table in module.DIRECT_TABLES:
            contracts[(table, f"rls_{table}_tenant_all")] = (
                "ALL", tenant, tenant,
            )
        for table in getattr(module, "GLOBAL_READ_TABLES", ()):
            contracts[(table, f"rls_{table}_context_select")] = (
                "SELECT", "app_current_organization_id() IS NOT NULL", None,
            )
    contracts[("jobs_job", "rls_jobs_job_tenant_all")] = ("ALL", tenant, tenant)
    parent = (
        "app_current_organization_id() IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM jobs_job parent WHERE parent.id = job_id "
        "AND parent.organization_id = app_current_organization_id())"
    )
    for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        using = parent if command in {"SELECT", "UPDATE", "DELETE"} else None
        check = parent if command in {"INSERT", "UPDATE"} else None
        contracts[(
            "jobs_jobattempt",
            f"rls_jobs_jobattempt_parent_{command.lower()}",
        )] = (command, using, check)
    return contracts
