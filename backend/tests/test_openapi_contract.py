from collections.abc import Iterable

import pytest
from rest_framework.test import APIClient


RESOURCE_TAGS = {
    "/api/v1/knowledge/concepts": "KnowledgeConcepts",
    "/api/v1/knowledge/relations": "KnowledgeRelations",
    "/api/v1/products": "Products",
    "/api/v1/assets": "Assets",
    "/api/v1/campaigns": "Campaigns",
    "/api/v1/content-briefs": "ContentBriefs",
    "/api/v1/master-contents": "MasterContents",
    "/api/v1/platform-contents": "PlatformContents",
    "/api/v1/publish-tasks": "PublishTasks",
    "/api/v1/tracking-links": "TrackingLinks",
    "/api/v1/short-links": "ShortLinks",
    "/api/v1/jobs": "Jobs",
    "/api/v1/auth": "Auth",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATION_METHODS = {"post", "put", "patch", "delete"}
ERROR_FIELDS = {"code", "message", "recovery_action"}


def _operations(schema: dict) -> Iterable[tuple[str, str, dict]]:
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def _shape(schema: dict, node: dict) -> tuple[set[str], set[str]]:
    if "$ref" in node:
        node = schema["components"]["schemas"][node["$ref"].rsplit("/", 1)[-1]]
    properties = set(node.get("properties", {}))
    required = set(node.get("required", []))
    for member in node.get("allOf", []):
        member_properties, member_required = _shape(schema, member)
        properties.update(member_properties)
        required.update(member_required)
    return properties, required


@pytest.fixture
def openapi_schema() -> dict:
    response = APIClient().get("/api/v1/schema")
    assert response.status_code == 200
    return response.json()


def test_required_resources_have_explicit_tags(openapi_schema: dict) -> None:
    operations = list(_operations(openapi_schema))
    for prefix, expected_tag in RESOURCE_TAGS.items():
        matching = [(path, method, operation) for path, method, operation in operations if path.startswith(prefix)]
        assert matching, f"No operations found for {prefix}"
        for path, method, operation in matching:
            assert expected_tag in operation.get("tags", []), f"{method.upper()} {path} is not tagged {expected_tag}"


def test_every_api_operation_has_a_non_default_resource_tag(openapi_schema: dict) -> None:
    for path, method, operation in _operations(openapi_schema):
        if not path.startswith("/api/v1/"):
            continue
        tags = operation.get("tags", [])
        assert tags and tags != ["api"], f"{method.upper()} {path} still uses a generated default tag"


def test_mutation_error_schemas_share_the_recoverable_envelope(openapi_schema: dict) -> None:
    for path, method, operation in _operations(openapi_schema):
        if not path.startswith("/api/v1/") or method not in MUTATION_METHODS:
            continue
        error_responses = [
            response
            for code, response in operation["responses"].items()
            if code.isdigit() and int(code) >= 400
        ]
        assert error_responses, f"{method.upper()} {path} has no documented error response"
        for response in error_responses:
            content = response.get("content", {}).get("application/json")
            assert content, f"{method.upper()} {path} has a non-JSON error contract"
            properties, required = _shape(openapi_schema, content["schema"])
            assert ERROR_FIELDS <= properties
            assert ERROR_FIELDS <= required


def test_runtime_mutation_errors_match_the_recoverable_envelope() -> None:
    response = APIClient().post("/api/v1/auth/login", {}, format="json")
    assert response.status_code == 400
    assert ERROR_FIELDS <= set(response.json())


def test_generated_method_field_types_match_runtime_values(openapi_schema: dict) -> None:
    schemas = openapi_schema["components"]["schemas"]
    assert schemas["MasterContent"]["properties"]["is_current_head"] == {
        "type": "boolean",
        "readOnly": True,
    }
    assert schemas["PlatformContent"]["properties"]["is_current_head"] == {
        "type": "boolean",
        "readOnly": True,
    }
    assert schemas["AIRun"]["properties"]["prompt"]["type"] == "object"


def test_every_local_schema_reference_resolves(openapi_schema: dict) -> None:
    schemas = openapi_schema["components"]["schemas"]

    def visit(node) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
                assert reference.rsplit("/", 1)[-1] in schemas, f"Unresolved schema reference: {reference}"
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(openapi_schema)
