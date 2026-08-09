import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Product, ProductConceptLink
from apps.catalog.services import build_product_snapshot, replace_product_links
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import KnowledgeConcept

from .conftest import make_concept
from .test_product_model import product_values


@pytest.mark.django_db
def test_direct_link_create_rechecks_stale_deprecated_concept(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="DIRECT_STALE_CREATE",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
    )
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=KnowledgeConcept.Status.DEPRECATED,
            version=2,
        )

    with pytest.raises(ValidationError, match="APPROVED"):
        ProductConceptLink._base_manager.create(
            organization=own,
            product=product,
            concept=concept,
            role=ProductConceptLink.Role.MATERIAL,
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_direct_link_bulk_create_rechecks_stale_deprecated_concept(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="DIRECT_STALE_BULK",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
    )
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=KnowledgeConcept.Status.DEPRECATED,
            version=2,
        )

    with pytest.raises(ValidationError, match="APPROVED"):
        ProductConceptLink._base_manager.bulk_create(
            [
                ProductConceptLink(
                    organization=own,
                    product=product,
                    concept=concept,
                    role=ProductConceptLink.Role.MATERIAL,
                )
            ]
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_direct_link_writes_lock_products_then_concepts_by_id(
    organizations, monkeypatch
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="DIRECT_LOCK_ORDER",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    observed = []
    original_select_for_update = QuerySet.select_for_update

    def tracking_select_for_update(queryset, *args, **kwargs):
        if queryset.model in {Product, KnowledgeConcept}:
            observed.append(
                (queryset.model, tuple(queryset.query.order_by), kwargs.get("of"))
            )
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", tracking_select_for_update)

    ProductConceptLink._base_manager.create(
        organization=own,
        product=product,
        concept=concept,
        role=ProductConceptLink.Role.MATERIAL,
    )

    assert observed == [
        (Product, ("id",), ("self",)),
        (KnowledgeConcept, ("id",), ("self",)),
    ]


@pytest.mark.django_db
def test_direct_link_create_rejects_archived_product(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(
        **product_values(own, status=Product.Status.ARCHIVED)
    )
    concept = make_concept(
        code="DIRECT_ARCHIVED_LINK",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )

    with pytest.raises(ValidationError, match="Archived"):
        ProductConceptLink._base_manager.create(
            organization=own,
            product=product,
            concept=concept,
            role=ProductConceptLink.Role.MATERIAL,
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_replace_product_links_rejects_changes_to_archived_product(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="ARCHIVED_SERVICE_LINK",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    replace_product_links(
        product=product,
        concept_links=[{"role": ProductConceptLink.Role.MATERIAL, "concept_id": concept.id}],
    )
    link = ProductConceptLink.objects.get(product=product)
    product.status = Product.Status.ARCHIVED
    product.save()

    with pytest.raises(ValidationError, match="Archived"):
        replace_product_links(product=product, concept_links=[])

    link.refresh_from_db()
    assert link.retired_at is None


@pytest.mark.django_db
def test_replace_product_links_allows_archived_exact_set_without_replacing_id(
    organizations,
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="ARCHIVED_SERVICE_NOOP",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    replace_product_links(
        product=product,
        concept_links=[{"role": ProductConceptLink.Role.MATERIAL, "concept_id": concept.id}],
    )
    link = ProductConceptLink.objects.get(product=product)
    product.status = Product.Status.ARCHIVED
    product.save()

    replace_product_links(
        product=product,
        concept_links=[{"role": ProductConceptLink.Role.MATERIAL, "concept_id": concept.id}],
    )

    assert ProductConceptLink.objects.active().get(product=product).id == link.id
    assert ProductConceptLink.objects.filter(product=product).count() == 1


@pytest.mark.django_db
def test_retired_link_instance_cannot_be_deleted(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="PROTECTED_RETIRED_INSTANCE",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    replace_product_links(
        product=product,
        concept_links=[{"role": ProductConceptLink.Role.MATERIAL, "concept_id": concept.id}],
    )
    replace_product_links(product=product, concept_links=[])
    link = ProductConceptLink.objects.get(product=product)

    with pytest.raises(ProtectedError):
        link.delete()

    assert ProductConceptLink.objects.filter(pk=link.pk).exists()


@pytest.mark.django_db
def test_retired_link_queryset_cannot_be_deleted(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="PROTECTED_RETIRED_QUERYSET",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    replace_product_links(
        product=product,
        concept_links=[{"role": ProductConceptLink.Role.MATERIAL, "concept_id": concept.id}],
    )
    replace_product_links(product=product, concept_links=[])
    link = ProductConceptLink.objects.get(product=product)

    with pytest.raises(ProtectedError):
        ProductConceptLink.objects.filter(pk=link.pk).delete()

    assert ProductConceptLink.objects.filter(pk=link.pk).exists()


@pytest.mark.django_db
def test_active_link_lock_query_does_not_join_concepts_and_targets_self(
    organizations, monkeypatch
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    concept = make_concept(
        code="LINK_LOCK_SHAPE",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=concept,
        role=ProductConceptLink.Role.MATERIAL,
    )
    lock_targets = []
    original_select_for_update = QuerySet.select_for_update

    def tracking_select_for_update(queryset, *args, **kwargs):
        if queryset.model is ProductConceptLink:
            lock_targets.append(kwargs.get("of"))
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", tracking_select_for_update)
    with CaptureQueriesContext(connection) as queries:
        snapshot = build_product_snapshot(product)

    link_queries = [
        item["sql"]
        for item in queries.captured_queries
        if 'FROM "catalog_productconceptlink"' in item["sql"]
    ]
    assert [item.concept_code for item in snapshot.concept_versions] == ["LINK_LOCK_SHAPE"]
    assert lock_targets == [("self",)]
    assert len(link_queries) == 1
    assert "JOIN" not in link_queries[0]
    assert 'ORDER BY "catalog_productconceptlink"."id" ASC' in link_queries[0]
