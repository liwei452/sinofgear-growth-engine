from collections import Counter

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
                "SELECT tablename, cmd FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = ANY(%s)",
                [list(RLS2A_TABLES)],
            )
            policies = {}
            for table, command in cursor.fetchall():
                policies.setdefault(table, []).append(command)
            cursor.execute(
                "SELECT rolname, rolinherit, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('sinofgear_owner', 'sinofgear_app')"
            )
            roles = {name: (inherit, bypass) for name, inherit, bypass in cursor.fetchall()}
            cursor.execute(
                "SELECT count(*) FROM pg_class table_object "
                "JOIN pg_roles owner ON owner.oid = table_object.relowner "
                "WHERE table_object.relname = ANY(%s) AND owner.rolname = 'sinofgear_app'",
                [list(RLS2A_TABLES)],
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

        errors = []
        missing = expected - shapes.keys()
        if missing:
            errors.append(f"database tables missing from RLS audit: {', '.join(sorted(missing))}")
        invalid = sorted(table for table, shape in shapes.items() if shape != (True, True))
        if invalid:
            errors.append(f"RLS is not enabled and forced: {', '.join(invalid)}")
        global_tables = {"ai_promptversion", "platforms_platform", "platforms_platformcapability"}
        for table in sorted(global_tables):
            if policies.get(table) != ["SELECT"]:
                errors.append(f"{table}: expected exactly one SELECT policy")
        for table in sorted(RLS2A_TABLES - global_tables - {"jobs_jobattempt"}):
            if policies.get(table) != ["ALL"]:
                errors.append(f"{table}: expected exactly one ALL policy")
        if sorted(policies.get("jobs_jobattempt", [])) != ["DELETE", "INSERT", "SELECT", "UPDATE"]:
            errors.append("jobs_jobattempt: expected SELECT/INSERT/UPDATE/DELETE policies")
        if roles.get("sinofgear_app") != (False, False):
            errors.append("sinofgear_app must be NOINHERIT and NOBYPASSRLS")
        if roles.get("sinofgear_owner") is None:
            errors.append("sinofgear_owner role is missing")
        if runtime_owned:
            errors.append("sinofgear_app owns one or more RLS-2A tables")
        if runtime_inherits_owner:
            errors.append("sinofgear_app can SET ROLE to sinofgear_owner")
        if not helper_executable:
            errors.append("sinofgear_app cannot execute app_current_organization_id()")
        if errors:
            raise CommandError("Database RLS audit failed:\n" + "\n".join(errors))
