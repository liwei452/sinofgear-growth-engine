import pytest
from apps.knowledge.models import KnowledgeConcept, KnowledgeRelation
from apps.knowledge.relation_rules import RelationRuleError

from .conftest import create_test_knowledge, make_concept


@pytest.mark.django_db
def test_capability_and_requirement_are_distinct_from_process(organizations):
    organization, _ = organizations

    capability = create_test_knowledge(
        KnowledgeConcept,
        scope=KnowledgeConcept.Scope.ORGANIZATION,
        organization=organization,
        code="CAP-GEAR-GRINDING",
        concept_type=KnowledgeConcept.ConceptType.CAPABILITY,
        label_zh="磨齿能力",
        label_en="Gear grinding capability",
        status=KnowledgeConcept.Status.APPROVED,
    )
    requirement = create_test_knowledge(
        KnowledgeConcept,
        scope=KnowledgeConcept.Scope.ORGANIZATION,
        organization=organization,
        code="REQ-DIN6",
        concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
        label_zh="DIN 6 精度要求",
        label_en="DIN 6 accuracy required",
        status=KnowledgeConcept.Status.APPROVED,
    )

    assert capability.concept_type == "CAPABILITY"
    assert requirement.concept_type == "REQUIREMENT"
    assert capability.concept_type != KnowledgeConcept.ConceptType.PROCESS


@pytest.mark.django_db
@pytest.mark.parametrize("subject_type", ["PRODUCT_TYPE", "CAPABILITY"])
def test_product_type_or_capability_satisfies_requirement(subject_type):
    subject = make_concept(code=f"SUBJECT_{subject_type}", concept_type=subject_type)
    requirement = make_concept(code=f"REQ_{subject_type}", concept_type="REQUIREMENT")

    relation = create_test_knowledge(
        KnowledgeRelation,
        organization=None,
        subject_concept=subject,
        predicate=KnowledgeRelation.Predicate.SATISFIES,
        object_concept=requirement,
        status=KnowledgeRelation.Status.APPROVED,
    )

    assert relation.predicate == "SATISFIES"


@pytest.mark.django_db
@pytest.mark.parametrize("subject_type", ["INDUSTRY", "APPLICATION"])
def test_industry_or_application_has_requirement(subject_type):
    subject = make_concept(code=f"SUBJECT_{subject_type}", concept_type=subject_type)
    requirement = make_concept(code=f"REQ_{subject_type}", concept_type="REQUIREMENT")

    relation = create_test_knowledge(
        KnowledgeRelation,
        organization=None,
        subject_concept=subject,
        predicate=KnowledgeRelation.Predicate.HAS_REQUIREMENT,
        object_concept=requirement,
        status=KnowledgeRelation.Status.APPROVED,
    )

    assert relation.predicate == "HAS_REQUIREMENT"


@pytest.mark.django_db
def test_requirement_relations_reject_reverse_direction():
    requirement = make_concept(code="REQ_REVERSE", concept_type="REQUIREMENT")
    capability = make_concept(code="CAP_REVERSE", concept_type="CAPABILITY")

    with pytest.raises(RelationRuleError, match="SATISFIES requires"):
        KnowledgeRelation.objects.create(
            organization=None,
            subject_concept=requirement,
            predicate="SATISFIES",
            object_concept=capability,
            status=KnowledgeRelation.Status.APPROVED,
        )
