import pytest

from apps.catalog.models import Product
from apps.identity.models import Role
from apps.knowledge.models import KnowledgeConcept

from .conftest import create_member_client, make_concept
from .test_products_api import api_product_payload


@pytest.mark.django_db
def test_get_exposes_etag_and_successful_patch_increments_version_once(
    organizations, roles
) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="patch-success"
    )
    created = client.post("/api/v1/products", api_product_payload(), format="json")
    product_id = created.json()["id"]

    fetched = client.get(f"/api/v1/products/{product_id}")
    patched = client.patch(
        f"/api/v1/products/{product_id}",
        {"name_en": "Updated Gear", "moq": 20},
        format="json",
        HTTP_IF_MATCH=fetched.headers["ETag"],
    )

    assert fetched.headers["ETag"] == '"1"'
    assert patched.status_code == 200, patched.json()
    assert patched.headers["ETag"] == '"2"'
    assert patched.json()["version"] == 2
    product = Product.objects.get(pk=product_id)
    assert product.version == 2
    assert product.name_en == "Updated Gear"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("header", "code"),
    [
        (None, "PRODUCT_VERSION_REQUIRED"),
        ("1", "PRODUCT_VERSION_INVALID"),
        ('W/"1"', "PRODUCT_VERSION_INVALID"),
        ('"not-an-integer"', "PRODUCT_VERSION_INVALID"),
        ('"0"', "PRODUCT_VERSION_INVALID"),
    ],
)
def test_missing_or_malformed_if_match_never_mutates(
    organizations, roles, header, code
) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username=f"precondition-{code}-{header}"
    )
    product_id = client.post(
        "/api/v1/products", api_product_payload(name_en="Before"), format="json"
    ).json()["id"]
    request_kwargs = {} if header is None else {"HTTP_IF_MATCH": header}

    response = client.patch(
        f"/api/v1/products/{product_id}",
        {"name_en": "After"},
        format="json",
        **request_kwargs,
    )

    assert response.status_code == 400
    assert response.json()["code"] == code
    product = Product.objects.get(pk=product_id)
    assert product.name_en == "Before"
    assert product.version == 1


@pytest.mark.django_db
def test_two_clients_editing_same_version_get_one_conflict_without_partial_change(
    organizations, roles
) -> None:
    own, _ = organizations
    _, first_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="concurrent-first"
    )
    _, second_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="concurrent-second"
    )
    product_id = first_client.post(
        "/api/v1/products", api_product_payload(name_en="Original"), format="json"
    ).json()["id"]

    first = first_client.patch(
        f"/api/v1/products/{product_id}",
        {"name_en": "First wins"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    stale = second_client.patch(
        f"/api/v1/products/{product_id}",
        {"name_en": "Stale loses", "moq": 999},
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json() == {"code": "PRODUCT_VERSION_CONFLICT", "current_version": 2}
    product = Product.objects.get(pk=product_id)
    assert product.name_en == "First wins"
    assert product.moq == 10
    assert product.version == 2


@pytest.mark.django_db
def test_patch_rolls_back_fields_version_and_links_when_replacement_fails(
    organizations, roles
) -> None:
    own, _ = organizations
    old = make_concept(code="OLD_TYPE", concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE)
    replacement = make_concept(
        code="REPLACEMENT_TYPE", concept_type=KnowledgeConcept.ConceptType.PRODUCT_TYPE
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="rollback-links"
    )
    created = client.post(
        "/api/v1/products",
        api_product_payload(
            name_en="Rollback Original",
            concept_links=[{"role": "TYPE", "concept_id": str(old.id)}],
        ),
        format="json",
    )
    product_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/products/{product_id}",
        {
            "name_en": "Must Roll Back",
            "concept_links": [
                {"role": "TYPE", "concept_id": str(replacement.id)},
                {"role": "TYPE", "concept_id": str(replacement.id)},
            ],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert response.status_code == 400
    product = Product.objects.get(pk=product_id)
    assert product.name_en == "Rollback Original"
    assert product.version == 1
    assert list(product.concept_links.values_list("concept_id", flat=True)) == [old.id]
