import pytest
from rest_framework.test import APIClient


PHASE_B1_PATHS = {
    "/api/v1/monitoring-targets",
    "/api/v1/ingestion-batches",
    "/api/v1/source-evidences",
    "/api/v1/source-signals",
    "/api/v1/source-contents",
    "/api/v1/lead-candidates",
    "/api/v1/lead-candidates/{candidate_id}",
    "/api/v1/lead-candidates/{candidate_id}/analyze",
    "/api/v1/lead-insights",
    "/api/v1/lead-reviews",
}


@pytest.mark.django_db
def test_openapi_schema_is_available() -> None:
    response = APIClient().get("/api/v1/schema")
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")


@pytest.mark.django_db
def test_openapi_schema_contains_the_complete_phase_b1_surface() -> None:
    response = APIClient().get("/api/v1/schema")
    assert response.status_code == 200
    assert PHASE_B1_PATHS <= set(response.json()["paths"])
