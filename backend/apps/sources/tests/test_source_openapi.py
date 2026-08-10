import pytest


pytestmark = pytest.mark.django_db


def test_source_openapi_operation_ids_and_methods_are_exact(operator_member_client):
    _member, client = operator_member_client
    response = client.get("/api/v1/schema")

    assert response.status_code == 200
    schema = response.json()
    expected = {
        "/api/v1/monitoring-targets": {
            "get": "monitoring_targets_list",
            "post": "monitoring_targets_create",
        },
        "/api/v1/ingestion-batches": {
            "get": "ingestion_batches_list",
            "post": "ingestion_batches_create",
        },
        "/api/v1/source-contents": {"get": "source_contents_list"},
        "/api/v1/source-signals": {"get": "source_signals_list"},
        "/api/v1/source-evidences": {"get": "source_evidences_list"},
        "/api/v1/source-evidences/{evidence_id}": {
            "get": "source_evidences_retrieve"
        },
    }
    for path, methods in expected.items():
        assert path in schema["paths"]
        assert {
            method: schema["paths"][path][method]["operationId"] for method in methods
        } == methods
        assert set(schema["paths"][path]) == set(methods)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/monitoring-targets",
        "/api/v1/ingestion-batches",
        "/api/v1/source-contents",
        "/api/v1/source-signals",
        "/api/v1/source-evidences",
    ],
)
def test_source_list_openapi_bounds_page_size(path, operator_member_client):
    _member, client = operator_member_client
    schema = client.get("/api/v1/schema").json()

    parameters = {
        parameter["name"]: parameter for parameter in schema["paths"][path]["get"]["parameters"]
    }
    assert parameters["page_size"]["schema"] == {
        "type": "integer",
        "maximum": 50,
        "minimum": 1,
    }
