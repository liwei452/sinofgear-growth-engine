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


def test_pending_candidate_can_be_reviewed_into_enrichment_without_creating_an_opportunity(organization):
    client = _client(organization, suffix="review")
    imported = client.post(
        IMPORT_URL,
        {
            "format": "CSV",
            "content": (
                "company_name,country,website,industry\n"
                "Jakarta Drives,Indonesia,https://jakarta.example.invalid,Industrial equipment\n"
            ),
            **_governance(),
        },
        format="json",
    )
    assert imported.status_code == 201
    candidate = DiscoveryCandidate.objects.get(organization=organization)

    workspace = client.get("/api/v1/growth/workspace")
    reviewed = client.post(
        f"/api/v1/growth/discovery/candidates/{candidate.id}/review",
        {"decision": "ACCEPT", "note": "官网与公司名称一致"},
        format="json",
    )

    assert workspace.status_code == 200
    assert workspace.data["discovery"]["candidates"] == [{
        "id": str(candidate.id),
        "company_name": "Jakarta Drives",
        "country": "Indonesia",
        "website": "https://jakarta.example.invalid/",
        "industry": "Industrial equipment",
        "status": "PENDING_REVIEW",
        "status_label": "待核实",
        "source_owner": "Licensed customer list supplier",
        "license_contract": "Internal prospecting licence 2026",
        "import_format": "CSV",
        "is_demo": False,
        "score": 0,
        "grade": "C",
        "intent_score": 0,
        "intent_breakdown": {},
        "created_at": candidate.created_at.isoformat().replace("+00:00", "Z"),
    }]
    assert reviewed.status_code == 200
    assert reviewed.data == {
        "id": str(candidate.id),
        "status": "ACCEPTED",
        "status_label": "待补全公司资料",
        "message": "已加入公司资料补全，不会自动联系客户。",
    }
    candidate.refresh_from_db()
    assert candidate.status == DiscoveryCandidate.Status.ACCEPTED
    assert candidate.review_note == "官网与公司名称一致"
    assert candidate.reviewed_at is not None
    assert candidate.reviewed_by.username == "candidate-import-review"
    assert TargetAccount.objects.filter(organization=organization).count() == 0


def test_candidate_review_is_single_decision_tenant_scoped_and_permissioned(organization):
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Cape Motion",
        country="South Africa",
        website="https://cape.example.invalid",
        import_format="CSV",
        source_governance=_governance(),
        raw_record={},
        record_hash="a" * 64,
    )
    operator = _client(organization, suffix="single")
    reader = _client(organization, reader=True, suffix="read-review")
    other = Organization.objects.create(name="Other tenant", slug="other-candidate-tenant")
    other_operator = _client(other, suffix="other-review")
    url = f"/api/v1/growth/discovery/candidates/{candidate.id}/review"

    forbidden = reader.post(url, {"decision": "DISMISS", "note": "不相关"}, format="json")
    hidden = other_operator.post(url, {"decision": "DISMISS", "note": "不相关"}, format="json")
    first = operator.post(url, {"decision": "DISMISS", "note": "整机厂，不采购齿轮"}, format="json")
    repeated = operator.post(url, {"decision": "ACCEPT", "note": "改变决定"}, format="json")

    assert forbidden.status_code == 403
    assert hidden.status_code == 404
    assert first.status_code == 200
    assert first.data["status_label"] == "已忽略"
    assert repeated.status_code == 409
    assert repeated.data["code"] == "CANDIDATE_ALREADY_REVIEWED"
