import os
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg.conninfo import conninfo_to_dict

from apps.common.tenancy import TenantContextError, tenant_atomic
from apps.knowledge.context_builder import build_mission_context
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import (
    KnowledgeAlias,
    KnowledgeConceptEvidence,
    KnowledgeEvidence,
    KnowledgeGraphLock,
    KnowledgeRelation,
    KnowledgeRelationEvidence,
)
from apps.knowledge.services import OntologyContextService

from .conftest import make_concept
from .test_knowledge_context_snapshot import make_context_sources


pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="RLS acceptance requires the dedicated PostgreSQL runtime-role settings.",
    ),
]

RLS_TABLES = {
    "knowledge_companyknowledgeprofile",
    "knowledge_companyfact",
    "knowledge_companyfactevidence",
    "knowledge_icpprofile",
    "knowledge_icpproductlink",
    "knowledge_websitepage",
    "knowledge_websitepageproductlink",
    "knowledge_websitepageconceptlink",
    "knowledge_knowledgecontextsnapshot",
    "knowledge_knowledgeevidence",
    "knowledge_knowledgeconcept",
    "knowledge_knowledgealias",
    "knowledge_knowledgerelation",
    "knowledge_knowledgeconcept_evidence",
    "knowledge_knowledgerelation_evidence",
}


def _runtime_parameters() -> dict[str, object]:
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


@pytest.fixture(autouse=True)
def ensure_graph_lock():
    KnowledgeGraphLock.objects.get_or_create(id=1, defaults={"name": "is_a_graph"})


def _set_tenant(runtime, organization_id) -> None:
    runtime.execute("BEGIN")
    runtime.execute(
        "SELECT set_config('app.current_organization_id', %s, true)",
        (str(organization_id),),
    )


def _create_evidence(organization, *, label: str) -> KnowledgeEvidence:
    with _test_fixture_writes():
        return KnowledgeEvidence.objects.create(
            organization=organization,
            evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
            excerpt=label,
            captured_at=timezone.now(),
            status=KnowledgeEvidence.Status.APPROVED,
        )


def _create_mixed_knowledge(organization, *, code: str):
    subject = make_concept(code=f"{code}_PRODUCT", organization=organization)
    target = make_concept(
        code=f"{code}_APPLICATION",
        concept_type=subject.ConceptType.APPLICATION,
        organization=organization,
    )
    evidence = _create_evidence(organization, label=code)
    with _test_fixture_writes():
        alias = KnowledgeAlias.objects.create(
            organization=organization,
            concept=subject,
            language="en",
            alias=f"{code} alias",
            status=KnowledgeAlias.Status.APPROVED,
        )
        relation = KnowledgeRelation.objects.create(
            organization=organization,
            subject_concept=subject,
            predicate=KnowledgeRelation.Predicate.APPLIES_TO,
            object_concept=target,
            status=KnowledgeRelation.Status.APPROVED,
        )
    concept_binding = KnowledgeConceptEvidence.objects.create(
        knowledgeconcept=subject,
        knowledgeevidence=evidence,
    )
    relation_binding = KnowledgeRelationEvidence.objects.create(
        knowledgerelation=relation,
        knowledgeevidence=evidence,
    )
    return {
        "concepts": {subject.id, target.id},
        "subject": subject,
        "evidence": evidence,
        "alias": alias,
        "relation": relation,
        "concept_binding": concept_binding,
        "relation_binding": relation_binding,
    }


def test_rls_is_forced_and_missing_context_denies_reads_and_writes(
    organizations,
    runtime_connection,
):
    organization, _ = organizations
    make_concept(code="PRIVATE", organization=organization)
    _create_mixed_knowledge(None, code="SYSTEM")

    rows = runtime_connection.execute(
        "SELECT relname, relrowsecurity, relforcerowsecurity "
        "FROM pg_class WHERE relname = ANY(%s)",
        (list(RLS_TABLES),),
    ).fetchall()
    assert {row[0] for row in rows} == RLS_TABLES
    assert all(row[1:] == (True, True) for row in rows)
    assert runtime_connection.execute(
        "SELECT count(*) FROM pg_class table_object "
        "JOIN pg_roles owner ON owner.oid = table_object.relowner "
        "WHERE table_object.relname = ANY(%s) AND owner.rolname = current_user",
        (list(RLS_TABLES),),
    ).fetchone() == (0,)
    assert runtime_connection.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = 'knowledge_knowledgegraphlock'"
    ).fetchone() == (False, False)
    assert runtime_connection.execute(
        "SELECT count(*) FROM knowledge_knowledgeconcept"
    ).fetchone() == (0,)
    for table in (
        "knowledge_knowledgeevidence",
        "knowledge_knowledgealias",
        "knowledge_knowledgerelation",
        "knowledge_knowledgeconcept_evidence",
        "knowledge_knowledgerelation_evidence",
    ):
        assert runtime_connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "INSERT INTO knowledge_knowledgeconcept "
            "(id, scope, organization_id, concept_type, code, label_zh, label_en, "
            "description, status, version, created_at, updated_at) "
            "VALUES (%s, 'ORGANIZATION', %s, 'INDUSTRY', 'DENIED', 'Denied', "
            "'Denied', '', 'SUGGESTED', 1, now(), now())",
            (uuid4(), organization.id),
        )


def test_tenant_reads_own_and_system_rows_but_cannot_mutate_other_or_system(
    organizations,
    runtime_connection,
):
    organization_a, organization_b = organizations
    own_rows = _create_mixed_knowledge(organization_a, code="OWN")
    foreign_rows = _create_mixed_knowledge(organization_b, code="FOREIGN")
    system_rows = _create_mixed_knowledge(None, code="SYSTEM")
    foreign = foreign_rows["subject"]
    system = system_rows["subject"]

    _set_tenant(runtime_connection, organization_a.id)
    visible_ids = {
        row[0]
        for row in runtime_connection.execute(
            "SELECT id FROM knowledge_knowledgeconcept"
        ).fetchall()
    }
    assert visible_ids == own_rows["concepts"] | system_rows["concepts"]
    table_expectations = {
        "knowledge_knowledgeevidence": {
            own_rows["evidence"].id,
            system_rows["evidence"].id,
        },
        "knowledge_knowledgealias": {
            own_rows["alias"].id,
            system_rows["alias"].id,
        },
        "knowledge_knowledgerelation": {
            own_rows["relation"].id,
            system_rows["relation"].id,
        },
        "knowledge_knowledgeconcept_evidence": {
            own_rows["concept_binding"].id,
            system_rows["concept_binding"].id,
        },
        "knowledge_knowledgerelation_evidence": {
            own_rows["relation_binding"].id,
            system_rows["relation_binding"].id,
        },
    }
    for table, expected_ids in table_expectations.items():
        visible_ids = {
            row[0]
            for row in runtime_connection.execute(f"SELECT id FROM {table}").fetchall()
        }
        assert visible_ids == expected_ids
    assert runtime_connection.execute(
        "UPDATE knowledge_knowledgeconcept SET label_en = 'Blocked' WHERE id = %s",
        (foreign.id,),
    ).rowcount == 0
    assert runtime_connection.execute(
        "DELETE FROM knowledge_knowledgeconcept WHERE id = %s",
        (foreign.id,),
    ).rowcount == 0
    assert runtime_connection.execute(
        "UPDATE knowledge_knowledgeconcept SET label_en = 'Blocked' WHERE id = %s",
        (system.id,),
    ).rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "INSERT INTO knowledge_knowledgeconcept "
            "(id, scope, organization_id, concept_type, code, label_zh, label_en, "
            "description, status, version, created_at, updated_at) "
            "VALUES (%s, 'ORGANIZATION', %s, 'INDUSTRY', 'CROSS', 'Cross', "
            "'Cross', '', 'SUGGESTED', 1, now(), now())",
            (uuid4(), organization_b.id),
        )
    runtime_connection.execute("ROLLBACK")


def test_parent_derived_policy_rejects_cross_tenant_association(
    organizations,
    runtime_connection,
):
    organization_a, organization_b = organizations
    concept_a = make_concept(code="A", organization=organization_a)
    concept_b = make_concept(code="B", organization=organization_b)
    evidence_a = _create_evidence(organization_a, label="A")
    evidence_b = _create_evidence(organization_b, label="B")
    KnowledgeGraphLock.objects.get_or_create(id=1, defaults={"name": "is_a_graph"})
    KnowledgeConceptEvidence.objects.create(
        knowledgeconcept=concept_a,
        knowledgeevidence=evidence_a,
    )

    _set_tenant(runtime_connection, organization_a.id)
    assert runtime_connection.execute(
        "SELECT count(*) FROM knowledge_knowledgeconcept_evidence"
    ).fetchone() == (1,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "INSERT INTO knowledge_knowledgeconcept_evidence "
            "(knowledgeconcept_id, knowledgeevidence_id) VALUES (%s, %s)",
            (concept_b.id, evidence_b.id),
        )
    runtime_connection.execute("ROLLBACK")


def test_transaction_local_context_clears_and_runtime_has_no_rls_bypass(
    organizations,
    runtime_connection,
):
    organization, _ = organizations
    owner_role = os.environ.get("RLS_TEST_OWNER_ROLE", "sinofgear_owner")

    for terminal_statement in ("COMMIT", "ROLLBACK"):
        _set_tenant(runtime_connection, organization.id)
        runtime_connection.execute(terminal_statement)
        assert runtime_connection.execute(
            "SELECT app_current_organization_id()"
        ).fetchone() == (None,)

    role_flags = runtime_connection.execute(
        "SELECT rolinherit, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert role_flags == (False, False)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(f'SET ROLE "{owner_role}"')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime_connection.execute(
            "ALTER TABLE knowledge_knowledgeconcept DISABLE ROW LEVEL SECURITY"
        )

    with _default_connection_as_runtime():
        with tenant_atomic(organization.id):
            with tenant_atomic(organization.id):
                assert connection.in_atomic_block
            with pytest.raises(TenantContextError, match="cannot switch"):
                with tenant_atomic(uuid4()):
                    pass
        with connection.cursor() as cursor:
            cursor.execute("SELECT app_current_organization_id()")
            assert cursor.fetchone() == (None,)


@contextmanager
def _default_connection_as_runtime():
    owner_settings = connection.settings_dict.copy()
    runtime_settings = _runtime_parameters()
    connection.close()
    connection.settings_dict.update(
        USER=runtime_settings.get("user", ""),
        PASSWORD=runtime_settings.get("password", ""),
        HOST=runtime_settings.get("host", ""),
        PORT=runtime_settings.get("port", ""),
    )
    try:
        yield
    finally:
        connection.close()
        connection.settings_dict.clear()
        connection.settings_dict.update(owner_settings)


def test_context_builder_is_idempotent_as_runtime_role(organizations):
    organization, _other, actor, _product, mission, _profile, _icp = make_context_sources(
        organizations
    )

    with _default_connection_as_runtime():
        first = build_mission_context(
            organization=organization,
            mission=mission,
            actor=actor,
        )
        repeated = build_mission_context(
            organization=organization,
            mission=mission,
            actor=actor,
        )

    assert repeated.id == first.id


def test_ontology_snapshot_enters_and_clears_runtime_tenant_context(organizations):
    organization, _ = organizations
    concept = make_concept(code="RUNTIME_CONTEXT", organization=organization)

    with _default_connection_as_runtime():
        snapshot = OntologyContextService(organization).build_snapshot(
            concept_ids=[concept.id],
            max_depth=0,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT app_current_organization_id()")
            current_organization_id = cursor.fetchone()[0]

    assert [item.concept_id for item in snapshot.concept_versions] == [concept.id]
    assert current_organization_id is None
