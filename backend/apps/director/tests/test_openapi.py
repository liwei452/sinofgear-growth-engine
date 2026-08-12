import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_openapi_exposes_cockpit_and_decision_operations():
    schema = APIClient().get("/api/v1/schema").json()
    cockpit = schema["paths"]["/api/v1/director/cockpit"]["get"]
    assert cockpit["operationId"] == "director_cockpit_retrieve"
    assert set(cockpit["responses"]) >= {"200", "401", "403"}
    for status_code in ("401", "403"):
        assert cockpit["responses"][status_code]["content"]["application/json"]["schema"]
    operation = schema["paths"]["/api/v1/director/proposals/{id}/decisions"]["post"]
    assert operation["operationId"] == "director_proposals_decisions_create"
    assert "requestBody" in operation
    assert set(operation["responses"]) >= {"200", "400", "401", "403", "404", "409"}
    for status_code in ("401", "403", "404"):
        assert operation["responses"][status_code]["content"]["application/json"]["schema"]
