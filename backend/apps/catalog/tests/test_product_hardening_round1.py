import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models.query import QuerySet
from django.utils import timezone
from rest_framework import serializers

from apps.catalog.models import Product, ProductConceptLink
from apps.catalog.serializers import ProductCreateSerializer, ProductSerializer
from apps.catalog.services import build_product_generation_context, build_product_snapshot
from apps.identity.models import Role
from apps.knowledge.guards import _test_fixture_writes
from apps.knowledge.models import KnowledgeConcept

from .conftest import create_member_client, make_concept
from .test_product_model import product_values
from .test_products_api import api_product_payload


@pytest.mark.django_db
def test_product_base_manager_cannot_bulk_create_invalid_capability_json(organizations) -> None:
    own, _ = organizations
    invalid = Product(
        **product_values(own, manufacturing_capabilities="opaque-not-a-list")
    )

    with pytest.raises(ValidationError):
        Product._base_manager.bulk_create([invalid])

    assert Product.objects.count() == 0


@pytest.mark.django_db
def test_link_base_manager_cannot_bulk_create_cross_organization_link(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    foreign = make_concept(
        code="BASE_MANAGER_FOREIGN",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )

    with pytest.raises(ValidationError):
        ProductConceptLink._base_manager.bulk_create(
            [
                ProductConceptLink(
                    organization=own,
                    product=product,
                    concept=foreign,
                    role=ProductConceptLink.Role.MATERIAL,
                )
            ]
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_link_base_manager_cannot_bulk_create_wrong_role_link(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    material = make_concept(
        code="BASE_MANAGER_WRONG_ROLE",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )

    with pytest.raises(ValidationError):
        ProductConceptLink._base_manager.bulk_create(
            [
                ProductConceptLink(
                    organization=own,
                    product=product,
                    concept=material,
                    role=ProductConceptLink.Role.TYPE,
                )
            ]
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"version": 2},
        {"retired_at": timezone.now()},
    ],
)
def test_new_links_must_start_active_at_version_one(organizations, overrides) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own))
    material = make_concept(
        code=f"INVALID_NEW_LINK_{len(overrides)}",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )

    with pytest.raises(ValidationError):
        ProductConceptLink._base_manager.bulk_create(
            [
                ProductConceptLink(
                    organization=own,
                    product=product,
                    concept=material,
                    role=ProductConceptLink.Role.MATERIAL,
                    **overrides,
                )
            ]
        )

    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_api_never_serializes_a_legacy_cross_organization_link(organizations, roles) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    visible = make_concept(
        code="VISIBLE_BEFORE_CORRUPTION",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    foreign = make_concept(
        code="FOREIGN_LEGACY_SECRET",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=visible,
        role=ProductConceptLink.Role.MATERIAL,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE catalog_productconceptlink SET concept_id = %s WHERE id = %s",
            [foreign.id.hex, link.id.hex],
        )
    _, client = create_member_client(
        organization=own,
        role=roles[Role.Code.ADMINISTRATOR],
        username="legacy-leak-reader",
    )

    response = client.get(f"/api/v1/products/{product.id}")

    assert response.status_code == 200
    assert response.json()["concept_links"] == []
    assert "FOREIGN_LEGACY_SECRET" not in response.content.decode()


@pytest.mark.django_db
def test_serializer_independently_rejects_an_unsafe_prefetched_link(organizations) -> None:
    own, other = organizations
    product = Product.objects.create(**product_values(own))
    visible = make_concept(
        code="SERIALIZER_VISIBLE",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    foreign = make_concept(
        code="SERIALIZER_FOREIGN_SECRET",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )
    link = ProductConceptLink.objects.create(
        organization=own,
        product=product,
        concept=visible,
        role=ProductConceptLink.Role.MATERIAL,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE catalog_productconceptlink SET concept_id = %s WHERE id = %s",
            [foreign.id.hex, link.id.hex],
        )
    product.active_concept_links = list(
        ProductConceptLink.objects.filter(product=product).select_related("concept")
    )

    serialized = ProductSerializer(product).data

    assert serialized["concept_links"] == []
    assert "SERIALIZER_FOREIGN_SECRET" not in str(serialized)


@pytest.mark.django_db
def test_create_rechecks_concept_after_validation_before_persisting_link(organizations) -> None:
    own, _ = organizations
    concept = make_concept(
        code="TOCTOU_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
    )
    serializer = ProductCreateSerializer(
        data=api_product_payload(
            concept_links=[{"role": "MATERIAL", "concept_id": str(concept.id)}]
        ),
        context={"organization": own},
    )
    assert serializer.is_valid(), serializer.errors
    with _test_fixture_writes():
        KnowledgeConcept.objects.filter(pk=concept.pk).update(
            status=KnowledgeConcept.Status.DEPRECATED,
            version=2,
        )

    with pytest.raises((ValidationError, serializers.ValidationError)):
        serializer.save()

    assert Product.objects.count() == 0
    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_link_persistence_locks_product_and_reread_concepts_in_stable_order(
    organizations, monkeypatch
) -> None:
    own, _ = organizations
    later = make_concept(
        code="LOCK_LATER", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    earlier = make_concept(
        code="LOCK_EARLIER", concept_type=KnowledgeConcept.ConceptType.STANDARD
    )
    lock_models = []
    original_select_for_update = QuerySet.select_for_update

    def tracking_select_for_update(queryset, *args, **kwargs):
        if queryset.model in {Product, KnowledgeConcept}:
            lock_models.append(queryset.model)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", tracking_select_for_update)
    serializer = ProductCreateSerializer(
        data=api_product_payload(
            concept_links=[
                {"role": "MATERIAL", "concept_id": str(later.id)},
                {"role": "STANDARD", "concept_id": str(earlier.id)},
            ]
        ),
        context={"organization": own},
    )
    assert serializer.is_valid(), serializer.errors

    product = serializer.save()

    assert product.concept_links.count() == 2
    assert lock_models[0] is Product
    assert KnowledgeConcept in lock_models


@pytest.mark.django_db
def test_unchanged_link_replacement_preserves_active_link_id(organizations, roles) -> None:
    own, _ = organizations
    concept = make_concept(
        code="UNCHANGED_LINK", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="unchanged-link"
    )
    created = client.post(
        "/api/v1/products",
        api_product_payload(
            concept_links=[{"role": "MATERIAL", "concept_id": str(concept.id)}]
        ),
        format="json",
    )
    original_link_id = created.json()["concept_links"][0]["id"]

    patched = client.patch(
        f"/api/v1/products/{created.json()['id']}",
        {
            "name_en": "Same Link Updated Product",
            "concept_links": [{"role": "MATERIAL", "concept_id": str(concept.id)}],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert patched.status_code == 200, patched.json()
    assert patched.json()["concept_links"][0]["id"] == original_link_id
    assert ProductConceptLink.objects.filter(product_id=created.json()["id"]).count() == 1


@pytest.mark.django_db
def test_removed_link_is_retired_and_readd_creates_new_active_history(organizations, roles) -> None:
    own, _ = organizations
    concept = make_concept(
        code="HISTORICAL_LINK", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="historical-link"
    )
    created = client.post(
        "/api/v1/products",
        api_product_payload(
            concept_links=[{"role": "MATERIAL", "concept_id": str(concept.id)}]
        ),
        format="json",
    )
    product_id = created.json()["id"]
    old_link_id = created.json()["concept_links"][0]["id"]

    removed = client.patch(
        f"/api/v1/products/{product_id}",
        {"concept_links": []},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    readded = client.patch(
        f"/api/v1/products/{product_id}",
        {"concept_links": [{"role": "MATERIAL", "concept_id": str(concept.id)}]},
        format="json",
        HTTP_IF_MATCH='"2"',
    )

    assert removed.status_code == 200
    assert removed.json()["concept_links"] == []
    assert readded.status_code == 200, readded.json()
    new_link_id = readded.json()["concept_links"][0]["id"]
    assert new_link_id != old_link_id
    old_link = ProductConceptLink.objects.get(pk=old_link_id)
    assert old_link.retired_at is not None
    assert ProductConceptLink.objects.get(pk=new_link_id).retired_at is None
    assert ProductConceptLink.objects.filter(product_id=product_id).count() == 2


@pytest.mark.django_db
def test_archiving_retains_links_and_rejects_conflicting_replacement(organizations, roles) -> None:
    own, _ = organizations
    concept = make_concept(
        code="ARCHIVE_LINK", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="archive-links"
    )
    created = client.post(
        "/api/v1/products",
        api_product_payload(
            concept_links=[{"role": "MATERIAL", "concept_id": str(concept.id)}]
        ),
        format="json",
    )
    product_id = created.json()["id"]
    link_id = created.json()["concept_links"][0]["id"]

    archived = client.patch(
        f"/api/v1/products/{product_id}",
        {"status": "ARCHIVED"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    conflict = client.patch(
        f"/api/v1/products/{product_id}",
        {"concept_links": []},
        format="json",
        HTTP_IF_MATCH='"2"',
    )

    assert archived.status_code == 200
    assert archived.json()["concept_links"][0]["id"] == link_id
    assert conflict.status_code == 400
    product = Product.objects.get(pk=product_id)
    assert product.status == Product.Status.ARCHIVED
    assert product.version == 2
    assert ProductConceptLink.objects.get(pk=link_id).retired_at is None


@pytest.mark.django_db
def test_snapshot_rereads_stale_product_and_current_active_links_atomically(
    organizations, roles, monkeypatch
) -> None:
    own, _ = organizations
    first = make_concept(
        code="STALE_FIRST", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    second = make_concept(
        code="STALE_SECOND", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="stale-snapshot"
    )
    created = client.post(
        "/api/v1/products",
        api_product_payload(
            name_en="Snapshot Before",
            concept_links=[{"role": "MATERIAL", "concept_id": str(first.id)}],
        ),
        format="json",
    )
    stale = Product.objects.get(pk=created.json()["id"])
    patched = client.patch(
        f"/api/v1/products/{stale.id}",
        {
            "name_en": "Snapshot After",
            "concept_links": [{"role": "MATERIAL", "concept_id": str(second.id)}],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert patched.status_code == 200
    locked_models = []
    original_select_for_update = QuerySet.select_for_update

    def tracking_select_for_update(queryset, *args, **kwargs):
        if queryset.model in {Product, KnowledgeConcept}:
            locked_models.append(queryset.model)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", tracking_select_for_update)

    snapshot = build_product_snapshot(stale)

    assert snapshot.name_en == "Snapshot After"
    assert snapshot.product_version == 2
    assert [item.concept_code for item in snapshot.concept_versions] == ["STALE_SECOND"]
    assert locked_models[0] is Product
    assert KnowledgeConcept in locked_models

    context = build_product_generation_context(stale)
    assert context.product.name_en == "Snapshot After"
    assert [item.concept_code for item in context.product.concept_versions] == [
        "STALE_SECOND"
    ]
    assert {item.concept_id for item in context.ontology.concept_versions} == {second.id}


@pytest.mark.django_db
def test_ordinary_product_writes_preserve_version_semantics(organizations) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own, name_en="Version One"))
    product.name_en = "Version Two"
    product.save()
    product.refresh_from_db()
    assert product.version == 2

    product.version = 99
    with pytest.raises(ValidationError, match="version"):
        product.save()
    with pytest.raises(ValidationError, match="version"):
        Product.objects.filter(pk=product.pk).update(version=99)
    product.refresh_from_db()
    product.version = 99
    with pytest.raises(ValidationError, match="version"):
        Product.objects.bulk_update([product], ["version"])
    product.refresh_from_db()
    assert product.version == 2


@pytest.mark.django_db
def test_ordinary_product_instance_and_queryset_writes_lock_rows(
    organizations, monkeypatch
) -> None:
    own, _ = organizations
    product = Product.objects.create(**product_values(own, name_en="Lock Version One"))
    product_locks = []
    original_select_for_update = QuerySet.select_for_update

    def tracking_select_for_update(queryset, *args, **kwargs):
        if queryset.model is Product:
            product_locks.append(True)
        return original_select_for_update(queryset, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", tracking_select_for_update)

    product.name_en = "Lock Version Two"
    product.save()
    Product.objects.filter(pk=product.pk).update(moq=11)

    product.refresh_from_db()
    assert product.version == 3
    assert product_locks


@pytest.mark.django_db
def test_cursor_pagination_is_stable_bounded_and_preserves_filters(organizations, roles) -> None:
    own, other = organizations
    concept = make_concept(
        code="PAGED_TYPE", concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE
    )
    _, own_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="paged-own"
    )
    _, other_client = create_member_client(
        organization=other, role=roles[Role.Code.OPERATOR], username="paged-other"
    )
    expected = []
    for index in range(5):
        response = own_client.post(
            "/api/v1/products",
            api_product_payload(
                name_en=f"Paged {index:02d}",
                concept_links=[{"role": "TYPE", "concept_id": str(concept.id)}],
            ),
            format="json",
        )
        expected.append(response.json()["id"])
    other_client.post(
        "/api/v1/products",
        api_product_payload(
            name_en="Paged Foreign",
            concept_links=[{"role": "TYPE", "concept_id": str(concept.id)}],
        ),
        format="json",
    )

    first_page = own_client.get("/api/v1/products?type=PAGED_TYPE&page_size=2")
    second_page = own_client.get(first_page.json()["next"])
    third_page = own_client.get(second_page.json()["next"])

    assert set(first_page.json()) == {"next", "previous", "results"}
    assert first_page.json()["previous"] is None
    assert "type=PAGED_TYPE" in first_page.json()["next"]
    assert "page_size=2" in first_page.json()["next"]
    assert second_page.json()["previous"] is not None
    assert third_page.json()["next"] is None
    actual = [
        item["id"]
        for page in (first_page, second_page, third_page)
        for item in page.json()["results"]
    ]
    assert actual == expected


@pytest.mark.django_db
def test_cursor_page_size_has_a_hard_maximum(organizations, roles) -> None:
    own, _ = organizations
    Product.objects.bulk_create(
        [
            Product(**product_values(own, name_en=f"Bounded {index:03d}"))
            for index in range(55)
        ]
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="bounded-page"
    )

    response = client.get("/api/v1/products?page_size=999")

    assert response.status_code == 200
    assert len(response.json()["results"]) == 50
    assert response.json()["next"] is not None


@pytest.mark.django_db
def test_filter_rejects_ambiguous_system_and_organization_code(organizations, roles) -> None:
    own, _ = organizations
    make_concept(
        code="AMBIGUOUS_TYPE", concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE
    )
    make_concept(
        code="AMBIGUOUS_TYPE",
        concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE,
        organization=own,
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="ambiguous-code"
    )

    response = client.get("/api/v1/products?type=AMBIGUOUS_TYPE")

    assert response.status_code == 400
    assert "ambiguous" in response.json()["errors"]["type"][0].lower()


@pytest.mark.django_db
def test_filter_rejects_uuid_identifier_colliding_with_exact_code(organizations, roles) -> None:
    own, _ = organizations
    identifier = uuid.uuid4()
    with _test_fixture_writes():
        KnowledgeConcept.objects.create(
            id=identifier,
            scope=KnowledgeConcept.Scope.SYSTEM,
            concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE,
            code="UUID_TARGET",
            label_zh="UUID target",
            label_en="UUID target",
            status=KnowledgeConcept.Status.APPROVED,
        )
        KnowledgeConcept.objects.create(
            scope=KnowledgeConcept.Scope.ORGANIZATION,
            organization=own,
            concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE,
            code=str(identifier),
            label_zh="UUID-looking code",
            label_en="UUID-looking code",
            status=KnowledgeConcept.Status.APPROVED,
        )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="uuid-code-collision"
    )

    response = client.get(f"/api/v1/products?type={identifier}")

    assert response.status_code == 400
    assert "ambiguous" in response.json()["errors"]["type"][0].lower()


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["status=ACTIVE&status=DRAFT", "type=A&type=B"])
def test_repeated_single_value_filters_are_rejected(organizations, roles, query) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username=f"repeated-{query[:4]}"
    )

    response = client.get(f"/api/v1/products?{query}")

    assert response.status_code == 400
    assert set(response.json()) == {"errors"}


@pytest.mark.django_db
def test_malformed_cursor_returns_documented_validation_error(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="bad-cursor"
    )

    response = client.get("/api/v1/products?cursor=not-a-valid-cursor")

    assert response.status_code == 400
    assert "cursor" in response.json()["errors"]
