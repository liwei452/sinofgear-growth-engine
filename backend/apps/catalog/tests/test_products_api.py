import uuid

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Product, ProductConceptLink
from apps.identity.models import Role
from apps.knowledge.models import KnowledgeConcept

from .conftest import create_member_client, make_concept


def api_product_payload(**overrides):
    payload = {
        "name_zh": "精密斜齿轮",
        "name_en": "Precision Helical Gear",
        "module_min": "0.5000",
        "module_max": "8.0000",
        "tooth_count_min": 8,
        "tooth_count_max": 240,
        "pressure_angle": "20.000",
        "accuracy_grade": "ISO 6",
        "heat_treatment": "Carburized",
        "surface_treatment": "Shot peened",
        "manufacturing_capabilities": ["hobbing", "grinding"],
        "inspection_capabilities": ["CMM"],
        "moq": 10,
        "lead_time": "4-6 weeks",
        "landing_page_url": "https://example.com/gears/helical",
        "status": "ACTIVE",
        "internal_notes": "Confidential margin target",
        "concept_links": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_anonymous_product_requests_are_denied() -> None:
    client = APIClient()

    assert client.get("/api/v1/products").status_code == 403
    assert client.post("/api/v1/products", api_product_payload(), format="json").status_code == 403
    assert client.get(f"/api/v1/products/{uuid.uuid4()}").status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("role_code", [Role.Code.ADMINISTRATOR, Role.Code.OPERATOR])
def test_administrator_and_operator_can_create_products_with_visible_approved_links(
    organizations, roles, role_code
) -> None:
    own, _ = organizations
    concept = make_concept(
        code=f"API_MATERIAL_{role_code}",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    _, client = create_member_client(
        organization=own, role=roles[role_code], username=f"writer-{role_code.lower()}"
    )

    response = client.post(
        "/api/v1/products",
        api_product_payload(
            concept_links=[{"role": "MATERIAL", "concept_id": str(concept.id)}]
        ),
        format="json",
    )

    assert response.status_code == 201, response.json()
    assert response.headers["ETag"] == '"1"'
    assert response.json()["organization"] == str(own.id)
    assert response.json()["version"] == 1
    assert response.json()["concept_links"][0]["role"] == "MATERIAL"
    assert response.json()["concept_links"][0]["concept"]["code"] == concept.code


@pytest.mark.django_db
@pytest.mark.parametrize("role_code", [Role.Code.REVIEWER, Role.Code.READ_ONLY])
def test_reviewer_and_read_only_can_read_but_not_write_products(
    organizations, roles, role_code
) -> None:
    own, _ = organizations
    admin = roles[Role.Code.ADMINISTRATOR]
    _, admin_client = create_member_client(
        organization=own, role=admin, username=f"admin-seed-{role_code.lower()}"
    )
    product_id = admin_client.post(
        "/api/v1/products", api_product_payload(), format="json"
    ).json()["id"]
    _, client = create_member_client(
        organization=own, role=roles[role_code], username=f"reader-{role_code.lower()}"
    )

    assert client.get("/api/v1/products").status_code == 200
    assert client.get(f"/api/v1/products/{product_id}").status_code == 200
    assert client.post("/api/v1/products", api_product_payload(), format="json").status_code == 403
    assert (
        client.patch(
            f"/api/v1/products/{product_id}",
            {"name_en": "Forbidden"},
            format="json",
            HTTP_IF_MATCH='"1"',
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_product_list_detail_create_and_update_are_organization_isolated(
    organizations, roles
) -> None:
    own, other = organizations
    _, own_client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username="own-admin"
    )
    _, other_client = create_member_client(
        organization=other, role=roles[Role.Code.ADMINISTRATOR], username="other-admin"
    )
    own_id = own_client.post(
        "/api/v1/products", api_product_payload(name_en="Own Product"), format="json"
    ).json()["id"]
    other_id = other_client.post(
        "/api/v1/products", api_product_payload(name_en="Other Product"), format="json"
    ).json()["id"]

    listed_ids = {item["id"] for item in own_client.get("/api/v1/products").json()["results"]}

    assert listed_ids == {own_id}
    assert own_client.get(f"/api/v1/products/{other_id}").status_code == 404
    assert (
        own_client.patch(
            f"/api/v1/products/{other_id}",
            {"name_en": "Leak"},
            format="json",
            HTTP_IF_MATCH='"1"',
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_create_rejects_foreign_nonapproved_and_duplicate_concept_links(
    organizations, roles
) -> None:
    own, other = organizations
    foreign = make_concept(
        code="FOREIGN_API_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=other,
    )
    suggested = make_concept(
        code="SUGGESTED_API_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
        organization=own,
        status=KnowledgeConcept.Status.SUGGESTED,
    )
    approved = make_concept(
        code="DUPLICATE_API_MATERIAL",
        concept_type=KnowledgeConcept.ConceptType.MATERIAL,
    )
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="link-isolation"
    )

    for links in (
        [{"role": "MATERIAL", "concept_id": str(foreign.id)}],
        [{"role": "MATERIAL", "concept_id": str(suggested.id)}],
        [
            {"role": "MATERIAL", "concept_id": str(approved.id)},
            {"role": "MATERIAL", "concept_id": str(approved.id)},
        ],
    ):
        response = client.post(
            "/api/v1/products", api_product_payload(concept_links=links), format="json"
        )
        assert response.status_code == 400
        assert set(response.json()) == {"errors"}

    assert Product.objects.count() == 0
    assert ProductConceptLink.objects.count() == 0


@pytest.mark.django_db
def test_api_validation_uses_stable_errors_envelope(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="invalid-product"
    )

    response = client.post(
        "/api/v1/products",
        api_product_payload(name_en=" ", landing_page_url="bad", moq=0),
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) == {"errors"}
    assert {"name_en", "landing_page_url", "moq"} <= set(response.json()["errors"])
