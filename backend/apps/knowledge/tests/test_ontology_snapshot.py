import dataclasses

import pytest

from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation
from apps.knowledge.services import OntologyContextService, OntologyDepthError
from apps.knowledge.guards import _test_fixture_writes

from .conftest import create_test_knowledge, make_concept


@pytest.fixture
def ontology_chain(organizations):
    own, _ = organizations
    first = make_concept(code="HELICAL_GEAR")
    second = make_concept(code="PACKAGING_LINE", concept_type="APPLICATION")
    third = make_concept(code="PACKAGING_INTENT", concept_type="PURCHASE_INTENT")
    hidden = make_concept(code="HIDDEN", concept_type="PARAMETER", status=KnowledgeConcept.Status.SUGGESTED)
    r1 = create_test_knowledge(
        KnowledgeRelation,
        subject_concept=first,
        predicate="APPLIES_TO",
        object_concept=second,
        status=KnowledgeRelation.Status.APPROVED,
    )
    r2 = create_test_knowledge(
        KnowledgeRelation,
        subject_concept=second,
        predicate="INDICATES_PURCHASE_INTENT",
        object_concept=third,
        status=KnowledgeRelation.Status.APPROVED,
    )
    KnowledgeRelation.objects.create(
        subject_concept=first,
        predicate="REQUIRES_PARAMETER",
        object_concept=hidden,
        status=KnowledgeRelation.Status.SUGGESTED,
    )
    evidence = create_test_knowledge(
        KnowledgeEvidence,
        evidence_type=KnowledgeEvidence.EvidenceType.PUBLIC_SOURCE,
        source_url="https://example.test/gears",
        excerpt="Frozen source excerpt",
        status=KnowledgeEvidence.Status.APPROVED,
    )
    first.evidence.add(evidence)
    r1.evidence.add(evidence)
    return own, first, second, third, hidden, r1, r2, evidence


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("depth", "codes", "relation_count"),
    [
        (0, ["HELICAL_GEAR"], 0),
        (1, ["HELICAL_GEAR", "PACKAGING_LINE"], 1),
        (2, ["HELICAL_GEAR", "PACKAGING_INTENT", "PACKAGING_LINE"], 2),
    ],
)
def test_expansion_depth_is_bounded_and_deterministic(ontology_chain, depth, codes, relation_count) -> None:
    own, first, *_ = ontology_chain

    snapshot = OntologyContextService(own).expand_concepts(concept_ids=[first.id], max_depth=depth)

    assert [item.code for item in snapshot.concept_versions] == codes
    assert len(snapshot.relation_versions) == relation_count


@pytest.mark.django_db
@pytest.mark.parametrize("depth", [-1, 3])
def test_expansion_rejects_depth_outside_zero_to_two(ontology_chain, depth) -> None:
    own, first, *_ = ontology_chain
    with pytest.raises(OntologyDepthError, match="between 0 and 2"):
        OntologyContextService(own).expand_concepts(concept_ids=[first.id], max_depth=depth)


@pytest.mark.django_db
def test_expansion_respects_an_explicit_empty_predicate_set(ontology_chain) -> None:
    own, first, *_ = ontology_chain

    snapshot = OntologyContextService(own).expand_concepts(
        concept_ids=[first.id], predicates=[], max_depth=2
    )

    assert [item.code for item in snapshot.concept_versions] == ["HELICAL_GEAR"]
    assert snapshot.relation_versions == ()


@pytest.mark.django_db
def test_snapshot_excludes_unapproved_knowledge_and_contains_approved_evidence(ontology_chain) -> None:
    own, first, _second, _third, hidden, _r1, _r2, evidence = ontology_chain
    snapshot = OntologyContextService(own).build_snapshot(concept_ids=[first.id], max_depth=2)

    assert hidden.id not in {item.concept_id for item in snapshot.concept_versions}
    assert {item.status for item in snapshot.concept_versions} == {KnowledgeConcept.Status.APPROVED}
    assert {item.status for item in snapshot.relation_versions} == {KnowledgeRelation.Status.APPROVED}
    assert [item.evidence_id for item in snapshot.evidence_references] == [evidence.id]


@pytest.mark.django_db
def test_snapshot_is_immutable_and_keeps_captured_versions(ontology_chain) -> None:
    own, first, *_ = ontology_chain
    snapshot = OntologyContextService(own).build_snapshot(concept_ids=[first.id], max_depth=1)
    first.version = 7
    first.status = KnowledgeConcept.Status.DEPRECATED
    with _test_fixture_writes():
        first.save()

    assert snapshot.concept_versions[0].version == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.organization_id = None


@pytest.mark.django_db
def test_expansion_never_traverses_other_organization_relations(organizations) -> None:
    own, other = organizations
    system = make_concept(code="SYSTEM")
    own_target = make_concept(code="OWN_TARGET", concept_type="APPLICATION", organization=own)
    foreign_target = make_concept(code="FOREIGN_TARGET", concept_type="APPLICATION", organization=other)
    create_test_knowledge(
        KnowledgeRelation,
        organization=own, subject_concept=system, predicate="APPLIES_TO", object_concept=own_target,
        status=KnowledgeRelation.Status.APPROVED,
    )
    create_test_knowledge(
        KnowledgeRelation,
        organization=other, subject_concept=system, predicate="APPLIES_TO", object_concept=foreign_target,
        status=KnowledgeRelation.Status.APPROVED,
    )

    snapshot = OntologyContextService(own).build_snapshot(concept_ids=[system.id], max_depth=1)

    assert [item.code for item in snapshot.concept_versions] == ["OWN_TARGET", "SYSTEM"]


@pytest.mark.django_db
@pytest.mark.parametrize("excluded_status", ["REJECTED", "DEPRECATED"])
def test_snapshot_independently_excludes_nonapproved_concepts_relations_and_evidence(
    organizations, excluded_status
) -> None:
    own, _ = organizations
    root = make_concept(code=f"ROOT_{excluded_status}")
    excluded = make_concept(code=f"CONCEPT_{excluded_status}", concept_type="APPLICATION", status=excluded_status)
    approved_target = make_concept(code=f"APPROVED_{excluded_status}", concept_type="APPLICATION")
    create_test_knowledge(
        KnowledgeRelation,
        subject_concept=root,
        predicate="APPLIES_TO",
        object_concept=excluded,
        status="APPROVED",
    )
    create_test_knowledge(
        KnowledgeRelation,
        subject_concept=root,
        predicate="APPLIES_TO",
        object_concept=approved_target,
        status=excluded_status,
    )
    evidence = create_test_knowledge(
        KnowledgeEvidence,
        evidence_type="HUMAN_ENTRY",
        excerpt=excluded_status,
        status=excluded_status,
    )
    root.evidence.add(evidence)

    snapshot = OntologyContextService(own).build_snapshot(concept_ids=[root.id, excluded.id], max_depth=1)

    assert excluded.id not in {item.concept_id for item in snapshot.concept_versions}
    assert excluded_status not in {item.status for item in snapshot.relation_versions}
    assert evidence.id not in {item.evidence_id for item in snapshot.evidence_references}
