from dataclasses import FrozenInstanceError, asdict

import pytest

from apps.catalog.models import Product, ProductConceptLink
from apps.catalog.services import build_product_generation_context, build_product_snapshot
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import KnowledgeConcept, KnowledgeEvidence, KnowledgeRelation

from .conftest import make_concept
from .test_product_model import product_values


@pytest.mark.django_db
def test_product_snapshot_is_deterministic_immutable_and_safe(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    material = make_concept(
        code="SNAPSHOT_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=material,
        role=ProductConceptLink.Role.MATERIAL,
    )

    first = build_product_snapshot(product)
    second = build_product_snapshot(Product.objects.get(pk=product.pk))

    assert first == second
    assert first["name_en"] == product.name_en
    assert first.manufacturing_capabilities == ("hobbing", "grinding")
    assert [item.concept_code for item in first.concept_versions] == ["SNAPSHOT_MATERIAL"]
    serialized = asdict(first)
    assert "organization_id" not in serialized
    assert "internal_notes" not in serialized
    assert "created_at" not in serialized
    assert "updated_at" not in serialized
    with pytest.raises(FrozenInstanceError):
        first.name_en = "Mutated"


@pytest.mark.django_db
def test_generation_context_uses_only_currently_approved_visible_ontology(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    product_type = make_concept(
        code="LINKED_TYPE", concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE
    )
    approved_application = make_concept(
        code="APPROVED_APPLICATION", concept_type=KnowledgeConcept.ConceptType.APPLICATION
    )
    suggested_application = make_concept(
        code="SUGGESTED_APPLICATION",
        concept_type=KnowledgeConcept.ConceptType.APPLICATION,
        status=KnowledgeConcept.Status.SUGGESTED,
    )
    approved_evidence = None
    rejected_evidence = None
    with _test_fixture_writes():
        approved_evidence = KnowledgeEvidence.objects.create(
            evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
            excerpt="Approved source",
            status=KnowledgeConcept.Status.APPROVED,
        )
        rejected_evidence = KnowledgeEvidence.objects.create(
            evidence_type=KnowledgeEvidence.EvidenceType.HUMAN_ENTRY,
            excerpt="Rejected source",
            status=KnowledgeConcept.Status.REJECTED,
        )
        relation = KnowledgeRelation.objects.create(
            subject_concept=product_type,
            predicate=KnowledgeRelation.Predicate.APPLIES_TO,
            object_concept=approved_application,
            status=KnowledgeConcept.Status.APPROVED,
        )
        KnowledgeRelation.objects.create(
            subject_concept=product_type,
            predicate=KnowledgeRelation.Predicate.APPLIES_TO,
            object_concept=suggested_application,
            status=KnowledgeConcept.Status.APPROVED,
        )
    relation.evidence.add(approved_evidence, rejected_evidence)
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=product_type,
        role=ProductConceptLink.Role.TYPE,
    )

    context = build_product_generation_context(product)

    concept_ids = {item.concept_id for item in context.ontology.concept_versions}
    evidence_ids = {item.evidence_id for item in context.ontology.evidence_references}
    assert product_type.id in concept_ids
    assert approved_application.id in concept_ids
    assert suggested_application.id not in concept_ids
    assert approved_evidence.id in evidence_ids
    assert rejected_evidence.id not in evidence_ids
    reference = context.product.concept_versions[0]
    assert reference.link_id == link.id
    assert reference.concept_version == product_type.version
    assert context.product.product_version == product.version


@pytest.mark.django_db
@pytest.mark.parametrize(
    "new_status",
    [
        KnowledgeConcept.Status.SUGGESTED,
        KnowledgeConcept.Status.REJECTED,
        KnowledgeConcept.Status.DEPRECATED,
    ],
)
def test_nonapproved_linked_concept_is_excluded_from_new_generation_context(
    organizations, new_status
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="LATER_DEPRECATED", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=concept,
        role=ProductConceptLink.Role.MATERIAL,
    )
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=new_status,
            version=2,
        )

    context = build_product_generation_context(product)

    assert context.product.concept_versions == ()
    assert context.ontology.concept_versions == ()
