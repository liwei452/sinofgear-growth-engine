import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Role


pytestmark = pytest.mark.django_db


def _client(organization, role, username):
    user = get_user_model().objects.create_user(username=username)
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_read_only_can_list_but_cannot_create_or_analyze(organization, candidate, evidence):
    client = _client(organization, Role.objects.create_read_only(), "lead-read-only")
    assert client.get("/api/v1/lead-candidates").status_code == 200
    assert client.post(
        "/api/v1/lead-candidates",
        {"company_name": "Denied", "evidence_ids": [str(evidence.id)]},
        format="json",
    ).status_code == 403
    assert client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(evidence.id)],
            "idempotency_key": "denied",
        },
        format="json",
    ).status_code == 403


def test_operator_cannot_review(organization, candidate):
    client = _client(organization, Role.objects.create_operator(), "lead-no-review")
    response = client.post(
        "/api/v1/lead-reviews",
        {
            "candidate_id": str(candidate.id),
            "action": "DISMISS",
            "expected_version": candidate.version,
            "reason": "Denied.",
            "idempotency_key": "operator-review-denied",
        },
        format="json",
    )
    assert response.status_code == 403


def test_reviewer_cannot_create_or_analyze(organization, candidate, evidence):
    client = _client(organization, Role.objects.create_reviewer(), "lead-review-only")
    assert client.post(
        "/api/v1/lead-candidates",
        {"company_name": "Denied", "evidence_ids": [str(evidence.id)]},
        format="json",
    ).status_code == 403
    assert client.post(
        f"/api/v1/lead-candidates/{candidate.id}/analyze",
        {
            "expected_version": candidate.version,
            "evidence_ids": [str(evidence.id)],
            "idempotency_key": "reviewer-analyze-denied",
        },
        format="json",
    ).status_code == 403
