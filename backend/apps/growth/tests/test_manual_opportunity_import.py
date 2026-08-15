import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import IntentSignal, TargetAccount
from apps.identity.models import Membership, Organization, Role


IMPORT_URL = "/api/v1/growth/opportunity-imports/manual-url"


def _client(organization, role_code=Role.Code.OPERATOR, suffix="owner"):
    role = {
        Role.Code.OPERATOR: Role.objects.create_operator,
        Role.Code.READ_ONLY: Role.objects.create_read_only,
    }[role_code]()
    user = get_user_model().objects.create_user(
        username=f"manual-opportunity-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


def _payload(**overrides):
    return {
        "company_name": "Buyer Systems GmbH",
        "country": "Germany",
        "industry": "Packaging machinery",
        "source_label": "Public company news",
        "source_url": "https://example.invalid/news/expansion",
        "evidence_text": "The company announced a new packaging line.",
        **overrides,
    }


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Manual opportunity", slug="manual-opportunity")


def test_operator_imports_permitted_evidence_as_a_conservative_real_opportunity(organization):
    response = _client(organization).post(IMPORT_URL, _payload(), format="json")

    assert response.status_code == 201
    assert response.data["created"] is True
    assert response.data["account"]["name"] == "Buyer Systems GmbH"
    assert response.data["account"]["data_label"] == "Licensed / permitted source"
    assert response.data["signal"]["collection_method"] == "MANUAL_URL"
    assert response.data["signal"]["collection_method_label"] == "人工导入网页"
    assert response.data["signal"]["confidence"] == 50
    assert response.data["signal"]["priority_label"] == "继续观察"
    assert response.data["signal"]["scoring_rule_version"] == "manual-opportunity-v1"
    assert response.data["signal"]["content_hash"] == (
        "48a8545300b0ee9cd550dafab4b43eccaceb82a9086d6acf547ccd20acbb65e1"
    )
    assert response.data["signal"]["score_breakdown"] == {
        "icp_fit": 15,
        "intent_strength": 15,
        "recency": 12,
        "role_relevance": 3,
        "evidence_coverage": 10,
        "risk_penalty": 5,
    }
    assert response.data["signal"]["uncertainty_notes"] == [
        "公司身份仍需人工核实",
        "采购范围与时间仍需人工确认",
    ]
    envelope = response.data["signal"]["evidence_envelope"]
    assert envelope["field_value"] == "The company announced a new packaging line."
    assert envelope["source_url"] == "https://example.invalid/news/expansion"
    assert envelope["source_excerpt"] == "The company announced a new packaging line."
    assert envelope["confidence"] == 50
    assert envelope["source_cost_micros"] == 0
    assert envelope["license_contract"] == "USER_ASSERTED_PERMISSION"
    assert envelope["usage_rights"] == "INTERNAL_DISCOVERY_WITH_SOURCE_LINK"
    assert envelope["review_status"] == "PENDING_REVIEW"
    assert envelope["queue"] == "MONITORING"
    assert envelope["source_type"] == "COMPANY_WEB"
    assert envelope["matched_keywords"] == []
    assert envelope["company_match_confidence"] == 50
    assert envelope["ai_exclusion_reasons"] == []
    assert envelope["observed_at"]
    assert TargetAccount.objects.filter(organization=organization, is_demo=False).count() == 1
    assert IntentSignal.objects.filter(organization=organization, is_demo=False).count() == 1


def test_duplicate_evidence_is_idempotent_and_does_not_cross_organizations(organization):
    client = _client(organization)
    first = client.post(IMPORT_URL, _payload(), format="json")
    duplicate = client.post(
        IMPORT_URL,
        _payload(company_name="A misleading replacement name"),
        format="json",
    )
    other = Organization.objects.create(name="Other manual", slug="other-manual")
    other_response = _client(other, suffix="other").post(IMPORT_URL, _payload(), format="json")

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.data["created"] is False
    assert duplicate.data["account"]["id"] == first.data["account"]["id"]
    assert IntentSignal.objects.filter(organization=organization).count() == 1
    assert TargetAccount.objects.filter(organization=organization).count() == 1
    assert other_response.status_code == 201
    assert other_response.data["account"]["id"] != first.data["account"]["id"]


@pytest.mark.parametrize(
    ("source_url", "invalid_fragment"),
    [
        ("http://example.invalid/news", "HTTPS"),
        ("https://user:secret@example.invalid/news", "用户名"),
        ("https://localhost/news", "公开"),
        ("https://buyer.local/news", "公开"),
        ("https://127.0.0.1/news", "公开"),
        ("https://10.0.0.1/news", "公开"),
        ("https://192.0.2.10/news", "公开"),
    ],
)
def test_import_rejects_unsafe_source_locators_without_partial_rows(
    organization, source_url, invalid_fragment,
):
    response = _client(organization, suffix=source_url.split("//", 1)[-1][:12]).post(
        IMPORT_URL, _payload(source_url=source_url), format="json",
    )

    assert response.status_code == 400
    assert invalid_fragment in response.data["message"]
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    assert IntentSignal.objects.filter(organization=organization).count() == 0


def test_import_requires_meaningful_evidence_and_manage_permission(organization):
    operator_response = _client(organization, suffix="blank").post(
        IMPORT_URL, _payload(evidence_text="short"), format="json",
    )
    reader_response = _client(
        organization, Role.Code.READ_ONLY, suffix="reader",
    ).post(IMPORT_URL, _payload(), format="json")

    assert operator_response.status_code == 400
    assert "至少" in operator_response.data["message"]
    assert reader_response.status_code == 403
    assert IntentSignal.objects.filter(organization=organization).count() == 0


def test_manual_import_is_documented_in_the_openapi_schema(organization):
    schema = _client(organization, suffix="schema").get("/api/v1/schema").json()

    operation = schema["paths"][IMPORT_URL]["post"]
    assert operation["tags"] == ["Growth workspace"]
    assert "requestBody" in operation
    assert "201" in operation["responses"]
