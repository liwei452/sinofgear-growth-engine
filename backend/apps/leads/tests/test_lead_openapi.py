import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Role


pytestmark = pytest.mark.django_db


def test_lead_openapi_operations_and_required_mutation_fields_are_exact(organization):
    user = get_user_model().objects.create_user(username="lead-schema-user")
    Membership.objects.create(
        user=user, organization=organization, role=Role.objects.create_administrator()
    )
    client = APIClient()
    client.force_authenticate(user)
    schema = client.get("/api/v1/schema").json()
    expected = {
        "/api/v1/lead-candidates": {
            "get": "lead_candidates_list",
            "post": "lead_candidates_create",
        },
        "/api/v1/lead-candidates/{candidate_id}": {
            "get": "lead_candidates_retrieve"
        },
        "/api/v1/lead-candidates/{candidate_id}/analyze": {
            "post": "lead_candidates_analyze"
        },
        "/api/v1/lead-insights": {"get": "lead_insights_list"},
        "/api/v1/lead-reviews": {"post": "lead_reviews_create"},
    }
    for path, methods in expected.items():
        assert path in schema["paths"]
        assert {
            method: schema["paths"][path][method]["operationId"] for method in methods
        } == methods
        assert set(schema["paths"][path]) == set(methods)

    components = schema["components"]["schemas"]
    assert set(components["LeadCandidateCreate"]["required"]) >= {
        "company_name",
        "evidence_ids",
    }
    assert set(components["LeadAnalyzeRequest"]["required"]) == {
        "evidence_ids",
        "expected_version",
        "idempotency_key",
    }
    assert set(components["LeadReviewCreate"]["required"]) >= {
        "action",
        "candidate_id",
        "expected_version",
        "idempotency_key",
        "reason",
    }


def test_lead_mutation_errors_use_recoverable_schema(organization):
    user = get_user_model().objects.create_user(username="lead-error-schema")
    Membership.objects.create(
        user=user, organization=organization, role=Role.objects.create_administrator()
    )
    client = APIClient()
    client.force_authenticate(user)
    schema = client.get("/api/v1/schema").json()
    error_schema = schema["components"]["schemas"]["LeadMutationError"]
    assert error_schema["required"] == ["code", "message", "recovery_action"]
    for path in (
        "/api/v1/lead-candidates",
        "/api/v1/lead-candidates/{candidate_id}/analyze",
        "/api/v1/lead-reviews",
    ):
        responses = schema["paths"][path]["post"]["responses"]
        assert "400" in responses and "403" in responses
