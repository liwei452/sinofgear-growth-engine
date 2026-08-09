from copy import deepcopy

from drf_spectacular.utils import OpenApiParameter


_MUTATION_METHODS = {"post", "put", "patch", "delete"}
_DEFAULT_ERRORS = {
    "400": "The request is invalid.",
    "401": "Authentication is required.",
    "403": "The request is forbidden or failed CSRF validation.",
}
_ERROR_REF = {"$ref": "#/components/schemas/ApiError"}


def bounded_integer_query_parameter(name: str, *, minimum: int, maximum: int | None = None):
    schema = {"type": "integer", "minimum": minimum}
    if maximum is not None:
        schema["maximum"] = maximum
    return OpenApiParameter(name, type=schema, location=OpenApiParameter.QUERY)


def _json_error_response(description: str, schema: dict | None = None) -> dict:
    response_schema = deepcopy(schema) if schema else deepcopy(_ERROR_REF)
    if response_schema != _ERROR_REF:
        response_schema = {"allOf": [deepcopy(_ERROR_REF), response_schema]}
    return {
        "description": description,
        "content": {"application/json": {"schema": response_schema}},
    }


def enforce_mutation_error_contract(result: dict, generator, request, public) -> dict:
    del generator, request, public
    for path, path_item in result.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            continue
        for method in _MUTATION_METHODS:
            operation = path_item.get(method)
            if not operation:
                continue
            responses = operation.setdefault("responses", {})
            for code, description in _DEFAULT_ERRORS.items():
                responses.setdefault(code, _json_error_response(description))
            for code, response in list(responses.items()):
                if not code.isdigit() or int(code) < 400:
                    continue
                content = response.get("content", {}).get("application/json")
                original_schema = content.get("schema") if content else None
                responses[code] = _json_error_response(
                    response.get("description") or "The request could not be completed.",
                    original_schema,
                )
    return result
