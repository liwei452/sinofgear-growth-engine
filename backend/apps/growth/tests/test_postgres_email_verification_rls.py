import hashlib
import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from django.db import connection
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from apps.growth.models import EmailVerificationEvidence, EmailVerificationRun
from apps.identity.models import Organization


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Email verification RLS acceptance requires PostgreSQL runtime role.",
    ),
]


def _runtime_parameters():
    try:
        parameters = conninfo_to_dict(os.environ["RLS_TEST_RUNTIME_DSN"])
    except KeyError:
        pytest.fail("RLS_TEST_RUNTIME_DSN is required for PostgreSQL RLS tests.")
    parameters["dbname"] = connection.settings_dict["NAME"]
    return parameters


@pytest.fixture(scope="session", autouse=True)
def grant_runtime_email_verification_access(django_db_setup, django_db_blocker):
    runtime_role = os.environ.get("RLS_TEST_RUNTIME_ROLE", "sinofgear_app")
    with django_db_blocker.unblock(), connection.cursor() as cursor:
        role = sql.Identifier(runtime_role)
        for table in (
            "growth_emailverificationrun",
            "growth_emailverificationevidence",
        ):
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                    sql.Identifier(table), role
                )
            )
        cursor.execute(
            sql.SQL(
                "REVOKE UPDATE, DELETE ON TABLE "
                "growth_emailverificationevidence FROM {}"
            ).format(role)
        )


@pytest.fixture
def runtime_connection():
    with psycopg.connect(**_runtime_parameters(), autocommit=True) as runtime:
        yield runtime


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


def _run(organization, key):
    email = f"{key}@example.com"
    return EmailVerificationRun.objects.create(
        organization=organization,
        normalized_email=email,
        email_fingerprint=hashlib.sha256(email.encode()).hexdigest(),
        domain="example.com",
        idempotency_key=key,
    )


def test_runtime_role_enforces_email_verification_tenant_and_append_only_boundaries(
    runtime_connection,
):
    own = Organization.objects.create(name="Email RLS A", slug=f"email-rls-a-{uuid.uuid4()}")
    other = Organization.objects.create(name="Email RLS B", slug=f"email-rls-b-{uuid.uuid4()}")
    own_run = _run(own, "own")
    other_run = _run(other, "other")
    evidence = EmailVerificationEvidence.objects.create(
        organization=own,
        run=own_run,
        sequence=1,
        check_type="MX",
        source="DNS",
        source_version="local-email-v1",
        outcome="PASS",
        reason_code="MX_FOUND",
        evidence={"mx_count": 1},
    )

    assert runtime_connection.execute(
        "SELECT count(*) FROM growth_emailverificationrun"
    ).fetchone() == (0,)

    with _tenant(runtime_connection, own.id):
        assert runtime_connection.execute(
            "SELECT id FROM growth_emailverificationrun ORDER BY id"
        ).fetchall() == [(own_run.id,)]
        assert runtime_connection.execute(
            "SELECT id FROM growth_emailverificationevidence"
        ).fetchall() == [(evidence.id,)]
        assert runtime_connection.execute(
            "UPDATE growth_emailverificationrun SET state = 'PAUSED' WHERE id = %s",
            (own_run.id,),
        ).rowcount == 1
        assert runtime_connection.execute(
            "UPDATE growth_emailverificationrun SET state = 'PAUSED' WHERE id = %s",
            (other_run.id,),
        ).rowcount == 0

    with pytest.raises(psycopg.errors.InsufficientPrivilege), _tenant(
        runtime_connection, own.id
    ):
        runtime_connection.execute(
            "INSERT INTO growth_emailverificationrun "
            "(id, organization_id, created_at, updated_at, normalized_email, "
            "email_fingerprint, domain, idempotency_key, state, reason_codes, "
            "verifier_version, result_source, requires_provider_review, "
            "request_snapshot, safe_error_code, attempt_count) "
            "VALUES (%s, %s, now(), now(), 'x@example.com', %s, 'example.com', "
            "'cross-insert', 'PENDING', '[]', 'local-email-v1', 'LOCAL', false, "
            "'{}', '', 0)",
            (uuid.uuid4(), other.id, "c" * 64),
        )

    with pytest.raises(psycopg.errors.InsufficientPrivilege), _tenant(
        runtime_connection, own.id
    ):
        runtime_connection.execute(
            "INSERT INTO growth_emailverificationevidence "
            "(id, organization_id, created_at, updated_at, sequence, check_type, "
            "source, source_version, outcome, reason_code, evidence, observed_at, run_id) "
            "VALUES (%s, %s, now(), now(), 1, 'MX', 'DNS', 'local-email-v1', "
            "'PASS', 'MX_FOUND', '{}', now(), %s)",
            (uuid.uuid4(), own.id, other_run.id),
        )

    for statement in (
        "UPDATE growth_emailverificationevidence SET outcome = 'FAIL' WHERE id = %s",
        "DELETE FROM growth_emailverificationevidence WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), _tenant(
            runtime_connection, own.id
        ):
            runtime_connection.execute(statement, (evidence.id,))
