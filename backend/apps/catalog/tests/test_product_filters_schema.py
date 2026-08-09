import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role
from apps.knowledge.models import KnowledgeConcept

from .conftest import create_member_client, make_concept
from .test_products_api import api_product_payload


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query_name", "role", "concept_type", "use_code"),
    [
        ("type", "TYPE", KnowledgeConcept.ConceptType.PRODUCT_TYPE, True),
        ("material", "MATERIAL", KnowledgeConcept.ConceptType.MATERIAL, False),
        ("application", "APPLICATION", KnowledgeConcept.ConceptType.APPLICATION, True),
    ],
)
def test_product_concept_filters_accept_visible_uuid_or_exact_code_without_leakage(
    organizations, roles, query_name, role, concept_type, use_code
) -> None:
    own, other = organizations
    concept = make_concept(code=f"FILTER_{role}", concept_type=concept_type)
    _, own_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username=f"filter-own-{role.lower()}"
    )
    _, other_client = create_member_client(
        organization=other,
        role=roles[Role.Code.OPERATOR],
        username=f"filter-other-{role.lower()}",
    )
    matched_id = own_client.post(
        "/api/v1/products",
        api_product_payload(
            name_en=f"Matched {role}",
            concept_links=[{"role": role, "concept_id": str(concept.id)}],
        ),
        format="json",
    ).json()["id"]
    own_client.post(
        "/api/v1/products", api_product_payload(name_en=f"Unmatched {role}"), format="json"
    )
    other_client.post(
        "/api/v1/products",
        api_product_payload(
            name_en=f"Foreign {role}",
            concept_links=[{"role": role, "concept_id": str(concept.id)}],
        ),
        format="json",
    )
    query_value = concept.code if use_code else str(concept.id)

    response = own_client.get(f"/api/v1/products?{query_name}={query_value}")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [matched_id]


@pytest.mark.django_db
def test_status_filter_is_exact_and_organization_scoped(organizations, roles) -> None:
    own, other = organizations
    _, own_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="status-own"
    )
    _, other_client = create_member_client(
        organization=other, role=roles[Role.Code.OPERATOR], username="status-other"
    )
    active_id = own_client.post(
        "/api/v1/products", api_product_payload(name_en="Active", status="ACTIVE"), format="json"
    ).json()["id"]
    own_client.post(
        "/api/v1/products", api_product_payload(name_en="Draft", status="DRAFT"), format="json"
    )
    other_client.post(
        "/api/v1/products", api_product_payload(name_en="Foreign Active", status="ACTIVE"), format="json"
    )

    response = own_client.get("/api/v1/products?status=ACTIVE")
    invalid = own_client.get("/api/v1/products?status=UNKNOWN")

    assert [item["id"] for item in response.json()["results"]] == [active_id]
    assert invalid.status_code == 400
    assert "status" in invalid.json()["errors"]


@pytest.mark.django_db
@pytest.mark.parametrize("detail", [False, True])
def test_product_link_serialization_has_bounded_query_counts(
    organizations, roles, django_assert_num_queries, detail
) -> None:
    own, _ = organizations
    material = make_concept(
        code="QUERY_MATERIAL", concept_type=KnowledgeConcept.ConceptType.MATERIAL
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username=f"query-{detail}"
    )
    product_ids = [
        client.post(
            "/api/v1/products",
            api_product_payload(
                name_en=f"Query Product {index}",
                concept_links=[{"role": "MATERIAL", "concept_id": str(material.id)}],
            ),
            format="json",
        ).json()["id"]
        for index in range(4)
    ]
    path = f"/api/v1/products/{product_ids[0]}" if detail else "/api/v1/products"

    with django_assert_num_queries(5):
        response = client.get(path)

    assert response.status_code == 200


@pytest.mark.django_db
def test_openapi_documents_product_contract_filters_etag_and_errors() -> None:
    schema = APIClient().get("/api/v1/schema").json()
    collection = schema["paths"]["/api/v1/products"]
    detail = schema["paths"]["/api/v1/products/{product_id}"]

    assert collection["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ProductList"
    )
    assert collection["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ProductCreate"
    )
    assert detail["patch"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "PatchedProductPatch"
    )
    assert {item["name"] for item in collection["get"]["parameters"]} == {
        "application",
        "cursor",
        "material",
        "page_size",
        "status",
        "type",
    }
    assert any(item["name"] == "If-Match" and item["in"] == "header" for item in detail["patch"]["parameters"])
    assert "ETag" in detail["get"]["responses"]["200"]["headers"]
    assert {"200", "400", "403", "404", "409"} <= set(detail["patch"]["responses"])


@pytest.mark.django_db
def test_runtime_product_validation_matches_documented_schema(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="schema-runtime"
    )

    response = client.post(
        "/api/v1/products", api_product_payload(status="UNKNOWN"), format="json"
    )
    schema = APIClient().get("/api/v1/schema").json()
    documented = schema["paths"]["/api/v1/products"]["post"]["responses"]["400"]

    assert response.status_code == 400
    assert set(response.json()) == {"errors"}
    assert isinstance(response.json()["errors"]["status"], list)
    assert documented["content"]["application/json"]["schema"]["$ref"].endswith(
        "ProductValidationError"
    )
