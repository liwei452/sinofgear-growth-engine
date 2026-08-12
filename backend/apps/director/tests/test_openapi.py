import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_exposes_cockpit_and_decision_operations():
    schema = APIClient().get("/api/v1/schema").json()
    assert schema["paths"]["/api/v1/director/cockpit"]["get"]["operationId"] == "director_cockpit_retrieve"
    operation = schema["paths"]["/api/v1/director/proposals/{id}/decisions"]["post"]
    assert operation["operationId"] == "director_proposals_decisions_create"
    assert "requestBody" in operation
    assert "200" in operation["responses"]
    assert "409" in operation["responses"]
