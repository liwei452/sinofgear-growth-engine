import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import DiscoveryCandidate, TargetAccount
from apps.identity.models import Membership, Organization, Role


IMPORT_URL = "/api/v1/growth/discovery/candidate-imports"


def _client(organization, *, reader=False, suffix="operator"):
    role = Role.objects.create_read_only() if reader else Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"candidate-import-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Candidate imports", slug="candidate-imports")


def _governance(**overrides):
    return {
        "source_owner": "Licensed customer list supplier",
        "license_contract": "Internal prospecting licence 2026",
        "retention_days": 90,
        "redistribution_allowed": False,
        **overrides,
    }


def test_csv_import_creates_only_discovery_candidates_with_governance(organization):
    content = (
        "company_name,country,website,industry\n"
        "Jakarta Drives,Indonesia,https://jakarta.example.invalid,Industrial equipment\n"
        "Cape Motion,South Africa,https://cape.example.invalid,Mining equipment\n"
    )

    response = _client(organization).post(
        IMPORT_URL,
        {"format": "CSV", "content": content, **_governance()},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["created_count"] == 2
    assert response.data["duplicate_count"] == 0
    assert response.data["invalid_count"] == 0
    assert response.data["queue_label"] == "待核实候选公司"
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    candidate = DiscoveryCandidate.objects.get(company_name="Jakarta Drives")
    assert candidate.status == "PENDING_REVIEW"
    assert candidate.import_format == "CSV"
    assert candidate.source_governance == {
        "source_owner": "Licensed customer list supplier",
        "access_method": "USER_UPLOAD",
        "license_contract": "Internal prospecting licence 2026",
        "robots_policy": "NOT_APPLICABLE_TO_CUSTOMER_LIST",
        "rate_limit": "NOT_APPLICABLE_TO_CUSTOMER_LIST",
        "allowed_fields": ["company_name", "country", "website", "industry"],
        "retention_days": 90,
        "redistribution_allowed": False,
    }


def test_json_import_is_idempotent_and_reports_invalid_rows(organization):
    content = json.dumps([
        {
            "company_name": "Chile Mining Gears",
            "country": "Chile",
            "website": "https://chile.example.invalid",
            "industry": "Mining",
        },
        {
            "company_name": "Unsafe Local Host",
            "country": "Chile",
            "website": "http://127.0.0.1/private",
            "industry": "Mining",
        },
    ])
    client = _client(organization, suffix="json")

    first = client.post(
        IMPORT_URL, {"format": "JSON", "content": content, **_governance()}, format="json",
    )
    duplicate = client.post(
        IMPORT_URL, {"format": "JSON", "content": content, **_governance()}, format="json",
    )

    assert first.status_code == 201
    assert first.data["created_count"] == 1
    assert first.data["invalid_count"] == 1
    assert first.data["errors"][0]["row"] == 2
    assert duplicate.status_code == 200
    assert duplicate.data["created_count"] == 0
    assert duplicate.data["duplicate_count"] == 1
    assert DiscoveryCandidate.objects.filter(organization=organization).count() == 1


def test_candidate_import_is_bounded_permissioned_and_documented(organization):
    oversized = json.dumps([
        {"company_name": f"Buyer {index}", "country": "Indonesia", "website": ""}
        for index in range(201)
    ])
    operator = _client(organization, suffix="bounded")
    reader = _client(organization, reader=True, suffix="reader")

    bounded = operator.post(
        IMPORT_URL, {"format": "JSON", "content": oversized, **_governance()}, format="json",
    )
    forbidden = reader.post(
        IMPORT_URL,
        {"format": "CSV", "content": "company_name,country\nBuyer,Chile\n", **_governance()},
        format="json",
    )
    schema = operator.get("/api/v1/schema").json()

    assert bounded.status_code == 400
    assert "最多 200" in bounded.data["message"]
    assert forbidden.status_code == 403
    assert "post" in schema["paths"][IMPORT_URL]
