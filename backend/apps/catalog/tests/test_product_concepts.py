import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.catalog.models import Product, ProductConceptLink
from apps.knowledge.models import KnowledgeConcept

from .conftest import make_concept
from .test_product_model import product_values


ROLE_TYPES = [
    (ProductConceptLink.Role.TYPE, KnowledgeConcept.ConceptType.PRODUCT_TYPE),
    (ProductConceptLink.Role.MATERIAL, KnowledgeConcept.ConceptType.MATERIAL),
    (ProductConceptLink.Role.PROCESS, KnowledgeConcept.ConceptType.PROCESS),
    (ProductConceptLink.Role.STANDARD, KnowledgeConcept.ConceptType.STANDARD),
    (ProductConceptLink.Role.APPLICATION, KnowledgeConcept.ConceptType.APPLICATION),
    (ProductConceptLink.Role.PARAMETER, KnowledgeConcept.ConceptType.PARAMETER),
    (ProductConceptLink.Role.CAPABILITY, KnowledgeConcept.ConceptType.CAPABILITY),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("role", "concept_type"), ROLE_TYPES)
def test_each_product_link_role_accepts_only_its_approved_concept_type(
    organizations, role, concept_type
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(code=f"VALID_{role}", concept_type=concept_type)

    link = ProductConceptLink.objects.create(
        organization=own, product=product, concept=concept, role=role
    )

    assert link.concept_id == concept.id


@pytest.mark.django_db
def test_application_role_accepts_normalized_industry_concepts(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    industry = make_concept(
        code="ROBOTICS_INDUSTRY",
        concept_type=KnowledgeConcept.ConceptType.INDUSTRY,
    )

    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=industry,
        role=ProductConceptLink.Role.APPLICATION,
    )

    assert link.concept_id == industry.id


@pytest.mark.django_db
@pytest.mark.parametrize(("role", "concept_type"), ROLE_TYPES)
def test_each_product_link_role_rejects_an_incompatible_concept_type(
    organizations, role, concept_type
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    wrong_type = (
        KnowledgeConcept.ConceptType.MATERIAL
        if concept_type != KnowledgeConcept.ConceptType.MATERIAL
        else KnowledgeConcept.ConceptType.PRODUCT_TYPE
    )
    concept = make_concept(code=f"WRONG_{role}", concept_type=wrong_type)

    with pytest.raises(ValidationError, match="compatible"):
        ProductConceptLink.objects.create(
            organization=own, product=product, concept=concept, role=role
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        KnowledgeConcept.Status.SUGGESTED,
        KnowledgeConcept.Status.REJECTED,
        KnowledgeConcept.Status.DEPRECATED,
    ],
)
def test_nonapproved_concepts_cannot_be_linked(organizations, status) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code=f"STATUS_{status}",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
        status=status,
    )

    with pytest.raises(ValidationError, match="APPROVED"):
        ProductConceptLink.objects.create(
            organization=own,
            product=product,
            concept=concept,
            role=ProductConceptLink.Role.MATERIAL,
        )


@pytest.mark.django_db
def test_cross_organization_product_concept_links_are_rejected(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="FOREIGN_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )

    with pytest.raises(ValidationError, match="organization"):
        ProductConceptLink.objects.create(
            organization=own,
            product=product,
            concept=concept,
            role=ProductConceptLink.Role.MATERIAL,
        )


@pytest.mark.django_db
def test_link_organization_must_match_product(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="OWN_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
    )

    with pytest.raises(ValidationError, match="organization"):
        ProductConceptLink.objects.create(
            organization=other,
            product=product,
            concept=concept,
            role=ProductConceptLink.Role.MATERIAL,
        )


@pytest.mark.django_db
def test_duplicate_role_concept_pair_is_rejected_deterministically(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="DUPLICATE_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    values = {
        "organization": own,
        "product": product,
        "concept": concept,
        "role": ProductConceptLink.Role.MATERIAL,
    }
    ProductConceptLink.objects.create(**values)

    with pytest.raises((ValidationError, IntegrityError)):
        with transaction.atomic():
            ProductConceptLink.objects.create(**values)


@pytest.mark.django_db
def test_bulk_and_queryset_paths_cannot_bypass_link_invariants(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    valid = make_concept(
        code="VALID_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    foreign = make_concept(
        code="FOREIGN_BULK_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=valid,
        role=ProductConceptLink.Role.MATERIAL,
    )

    with pytest.raises(ValidationError):
        ProductConceptLink.objects.bulk_create(
            [
                ProductConceptLink(
                    organization=own,
                    product=product,
                    concept=foreign,
                    role=ProductConceptLink.Role.MATERIAL,
                )
            ]
        )
    with pytest.raises(ValidationError):
        ProductConceptLink.objects.filter(pk=link.pk).update(concept=foreign)


@pytest.mark.django_db
def test_raw_foreign_key_bulk_paths_cannot_use_stale_relation_caches(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    valid = make_concept(
        code="RAW_VALID_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    foreign = make_concept(
        code="RAW_FOREIGN_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=valid,
        role=ProductConceptLink.Role.MATERIAL,
    )

    with pytest.raises(ValidationError):
        ProductConceptLink.objects.filter(pk=link.pk).update(concept_id=foreign.id)
    link.concept_id = foreign.id
    with pytest.raises(ValidationError):
        ProductConceptLink.objects.bulk_update([link], ["concept"])
    assert ProductConceptLink.objects.get(pk=link.pk).concept_id == valid.id


@pytest.mark.django_db
def test_link_identity_is_immutable_so_snapshot_references_stay_stable(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    original = make_concept(
        code="IMMUTABLE_ORIGINAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    replacement = make_concept(
        code="IMMUTABLE_REPLACEMENT", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=original,
        role=ProductConceptLink.Role.MATERIAL,
    )
    link.concept = replacement

    with pytest.raises(ValidationError, match="immutable"):
        link.save()

    link.refresh_from_db()
    assert link.concept_id == original.id


@pytest.mark.django_db
def test_product_has_no_unsafe_m2m_concept_mutation_surface(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))

    with pytest.raises(AttributeError):
        _ = product.concepts


@pytest.mark.django_db
def test_linked_concept_is_protected_from_deletion(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="PROTECTED_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=concept,
        role=ProductConceptLink.Role.MATERIAL,
    )

    with pytest.raises(ProtectedError):
        concept.delete()
