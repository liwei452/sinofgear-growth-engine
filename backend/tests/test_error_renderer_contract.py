import json
from types import SimpleNamespace

import pytest
from django.urls import path
from django.test import override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.common.renderers import RecoverableErrorJSONRenderer, recoverable_error


UNSAFE_ERROR = {
    "code": "database_connection_failed",
    "detail": "postgres password=SUPER-SECRET",
    "message": "internal host db.internal",
    "recovery_action": "inspect trace id secret-trace",
    "errors": {"nested": {"api_key": "NESTED-SECRET"}},
    "trace": ["SECRET-FRAME"],
}
SAFE_500_ERROR = {
    "code": "internal_server_error",
    "message": "The server could not complete the request.",
    "recovery_action": "Try again later.",
}


class UnsafeMutationView(APIView):
    def post(self, request):
        return Response(UNSAFE_ERROR, status=500)


urlpatterns = [path("unsafe-mutation", UnsafeMutationView.as_view())]


def test_direct_mutation_5xx_normalization_discards_every_source_field() -> None:
    assert recoverable_error(UNSAFE_ERROR, 500) == SAFE_500_ERROR


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_api_render_pipeline_never_serializes_nested_mutation_5xx_secrets() -> None:
    response = APIClient().post("/unsafe-mutation", {}, format="json")

    assert response.status_code == 500
    assert response.json() == SAFE_500_ERROR
    serialized = response.content.decode()
    for secret in ("SUPER-SECRET", "db.internal", "secret-trace", "NESTED-SECRET", "SECRET-FRAME"):
        assert secret not in serialized


def test_renderer_keeps_4xx_extensions_and_does_not_change_get_errors() -> None:
    renderer = RecoverableErrorJSONRenderer()
    mutation = json.loads(renderer.render(
        {"detail": "Fix this value.", "errors": {"name": ["Required."]}, "current_version": 3},
        renderer_context={
            "response": SimpleNamespace(status_code=409),
            "request": SimpleNamespace(method="PATCH"),
        },
    ))
    read_error = json.loads(renderer.render(
        {"detail": "Read detail stays unchanged."},
        renderer_context={
            "response": SimpleNamespace(status_code=500),
            "request": SimpleNamespace(method="GET"),
        },
    ))

    assert mutation["detail"] == "Fix this value."
    assert mutation["errors"] == {"name": ["Required."]}
    assert mutation["current_version"] == 3
    assert {"code", "message", "recovery_action"} <= set(mutation)
    assert read_error == {"detail": "Read detail stays unchanged."}
