import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.knowledge.models import KnowledgeConcept, KnowledgeRelation
from apps.knowledge.relation_rules import PREDICATE_TYPE_RULES, RelationCycleError, RelationRuleError
from apps.knowledge.services import KnowledgeRelationService, OntologyContextService

from .conftest import make_concept


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("predicate", "subject_type", "object_type"),
    [
        ("IS_A", "PRODUCT_TYPE", "PRODUCT_TYPE"),
        ("APPLIES_TO", "PRODUCT_TYPE", "APPLICATION"),
        ("USES_MATERIAL", "PRODUCT_TYPE", "MATERIAL"),
        ("REQUIRES_PROCESS", "PRODUCT_TYPE", "PROCESS"),
        ("COMPLIES_WITH", "PRODUCT_TYPE", "STANDARD"),
        ("RELEVANT_TO_CUSTOMER_TYPE", "PRODUCT_TYPE", "CUSTOMER_TYPE"),
        ("INDICATES_PURCHASE_INTENT", "APPLICATION", "PURCHASE_INTENT"),
        ("REQUIRES_PARAMETER", "PRODUCT_TYPE", "PARAMETER"),
    ],
)
def test_every_predicate_accepts_its_documented_type_rule(
    organizations, predicate, subject_type, object_type
) -> None:
    subject = make_concept(code=f"S_{predicate}", concept_type=subject_type)
    object_ = make_concept(code=f"O_{predicate}", concept_type=object_type)

    relation = KnowledgeRelationService(organizations[0]).create(
        subject=subject, predicate=predicate, object=object_
    )

    assert relation.predicate == predicate
    assert predicate in PREDICATE_TYPE_RULES


@pytest.mark.django_db
def test_invalid_predicate_type_pair_reports_allowed_types(organizations) -> None:
    material = make_concept(code="STEEL", concept_type=KnowledgeConcept.ConceptType.MATERIAL)
    standard = make_concept(code="DIN", concept_type=KnowledgeConcept.ConceptType.STANDARD)

    with pytest.raises(RelationRuleError, match="USES_MATERIAL.*PRODUCT_TYPE.*MATERIAL"):
        KnowledgeRelationService(organizations[0]).create(
            subject=material, predicate=KnowledgeRelation.Predicate.USES_MATERIAL, object=standard
        )


@pytest.mark.django_db
def test_duplicate_system_relation_is_rejected(organizations) -> None:
    gear = make_concept(code="GEAR")
    application = make_concept(code="CONVEYOR", concept_type=KnowledgeConcept.ConceptType.APPLICATION)
    service = KnowledgeRelationService(organizations[0])
    service.create(subject=gear, predicate="APPLIES_TO", object=application)

    with pytest.raises(IntegrityError):
        service.create(subject=gear, predicate="APPLIES_TO", object=application)


@pytest.mark.django_db
def test_multi_hop_is_a_cycle_is_rejected_with_useful_cycle_path(organizations) -> None:
    gear = make_concept(code="GEAR")
    helical = make_concept(code="HELICAL_GEAR")
    ground_helical = make_concept(code="GROUND_HELICAL_GEAR")
    service = KnowledgeRelationService(organizations[0])
    service.create(subject=helical, predicate="IS_A", object=gear)
    service.create(subject=ground_helical, predicate="IS_A", object=helical)

    with pytest.raises(RelationCycleError) as error:
        service.create(subject=gear, predicate="IS_A", object=ground_helical)

    assert error.value.path == ["GEAR", "GROUND_HELICAL_GEAR", "HELICAL_GEAR", "GEAR"]


@pytest.mark.django_db
def test_relation_cannot_link_another_organizations_concept(organizations) -> None:
    own, other = organizations
    subject = make_concept(code="OWN", organization=own)
    foreign = make_concept(code="FOREIGN_APP", concept_type="APPLICATION", organization=other)

    with pytest.raises(ValidationError, match="visible"):
        KnowledgeRelationService(own).create(subject=subject, predicate="APPLIES_TO", object=foreign)

    assert list(OntologyContextService(own).visible_relations()) == []


@pytest.mark.django_db
def test_ai_originated_relation_cannot_be_created_as_approved(organizations) -> None:
    import uuid

    subject = make_concept(code="AI_PRODUCT")
    object_ = make_concept(code="AI_APPLICATION", concept_type="APPLICATION")

    with pytest.raises(ValidationError, match="AI-originated"):
        KnowledgeRelationService(organizations[0]).create(
            subject=subject,
            predicate="APPLIES_TO",
            object=object_,
            status="APPROVED",
            suggested_by_ai_run_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_system_is_a_checks_every_organization_overlay(organizations) -> None:
    own, other = organizations
    parent = make_concept(code="PARENT")
    child = make_concept(code="CHILD")
    KnowledgeRelationService(other).create(
        subject=child,
        predicate="IS_A",
        object=parent,
        scope="ORGANIZATION",
    )

    with pytest.raises(RelationCycleError) as error:
        KnowledgeRelationService(own).create(
            subject=parent,
            predicate="IS_A",
            object=child,
            scope="SYSTEM",
        )

    assert error.value.path == ["PARENT", "CHILD", "PARENT"]
    assert error.value.organization_id == other.id


@pytest.mark.django_db
def test_competing_graph_writes_use_the_same_deterministic_concept_lock_set(organizations) -> None:
    first = make_concept(code="LOCK_A")
    second = make_concept(code="LOCK_B")
    service = KnowledgeRelationService(organizations[0])

    forward = service.graph_lock_concept_ids(subject=first, object=second)
    reverse = service.graph_lock_concept_ids(subject=second, object=first)

    assert forward == reverse == tuple(sorted((first.id, second.id), key=str))
