import pytest
from rest_framework.test import APIClient

from apps.identity.models import Role

from .conftest import create_member_client, upload_payload


@pytest.mark.django_db
def test_openapi_documents_asset_requests_filters_actions_and_errors() -> None:
    schema = APIClient().get("/api/v1/schema").json()
    collection = schema["paths"]["/api/v1/assets"]
    detail = schema["paths"]["/api/v1/assets/{asset_id}"]
    link = schema["paths"]["/api/v1/assets/{asset_id}/link-product"]
    download = schema["paths"]["/api/v1/assets/{asset_id}/download-url"]

    assert "multipart/form-data" in collection["post"]["requestBody"]["content"]
    assert {item["name"] for item in collection["get"]["parameters"]} == {
        "cursor",
        "page_size",
        "product",
        "status",
        "tag",
        "type",
    }
    assert collection["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("AssetList")
    assert detail["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"].endswith("MaterialAsset")
    assert {"200", "400", "403", "404"} <= set(link["post"]["responses"])
    assert {"200", "403", "404"} <= set(download["post"]["responses"])


@pytest.mark.django_db
def test_runtime_upload_validation_matches_documented_error_shape(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="asset-schema-runtime"
    )

    response = client.post(
        "/api/v1/assets",
        upload_payload(asset_type="UNKNOWN"),
        format="multipart",
    )
    schema = APIClient().get("/api/v1/schema").json()
    documented = schema["paths"]["/api/v1/assets"]["post"]["responses"]["400"]

    assert response.status_code == 400
    assert set(response.json()) == {"errors", "code", "message", "recovery_action"}
    assert isinstance(response.json()["errors"]["asset_type"], list)
    refs = {
        item["$ref"].rsplit("/", 1)[-1]
        for item in documented["content"]["application/json"]["schema"]["allOf"]
    }
    assert refs == {"ApiError", "AssetValidationError"}
