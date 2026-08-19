import hashlib

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import IntentSignal, OpportunityReview, TargetAccount
from apps.identity.models import Membership, Organization, Role


def _client(organization, suffix="operator"):
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"opportunity-review-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def opportunity(db):
    organization = Organization.objects.create(
        name="Opportunity review", slug="opportunity-review",
    )
    account = TargetAccount.objects.create(
        organization=organization,
        name="Evidence Buyer",
        country="Indonesia",
        industry="Industrial equipment",
        website="https://buyer.example.invalid",
    )
    evidence_text = "Buyer published a tender for custom helical gear components."
    signal = IntentSignal.objects.create(
        organization=organization,
        account=account,
        signal_type="PROCUREMENT_NOTICE",
        source_label="Official tender",
        source_url="https://tender.example.invalid/notices/gear-1",
        evidence_text=evidence_text,
        confidence=82,
        collection_method="OFFICIAL_PUBLIC_API",
        content_hash=hashlib.sha256(evidence_text.encode()).hexdigest(),
        score_breakdown={
            "icp_fit": 20,
            "intent_strength": 23,
            "recency": 14,
            "role_relevance": 10,
            "evidence_coverage": 17,
            "risk_penalty": 2,
        },
        uncertainty_notes=["采购数量仍需人工确认"],
        evidence_envelope={
            "source_url": "https://tender.example.invalid/notices/gear-1",
            "source_excerpt": evidence_text,
            "source_type": "TENDER",
            "review_status": "PENDING_REVIEW",
            "license_contract": "OFFICIAL_OPEN_DATA_TERMS",
            "usage_rights": "INTERNAL_DISCOVERY_WITH_SOURCE_LINK",
        },
    )
    return organization, account, signal


def test_human_decisions_append_history_without_overwriting_the_signal(opportunity):
    organization, account, signal = opportunity
    client = _client(organization)
    url = f"/api/v1/growth/opportunities/{account.id}/review"

    first = client.post(url, {"decision": "PRIORITIZE"}, format="json")
    second = client.post(url, {"decision": "OBSERVE"}, format="json")

    assert first.status_code == 201
    assert first.data["status_label"] == "优先跟进"
    assert second.status_code == 201
    assert second.data["status_label"] == "继续观察"
    assert OpportunityReview.objects.filter(account=account).count() == 2
    signal.refresh_from_db()
    assert signal.confidence == 82
    assert signal.score_breakdown["intent_strength"] == 23


def test_mock_crm_handoff_requires_priority_review_and_complete_evidence(opportunity):
    organization, account, signal = opportunity
    client = _client(organization, suffix="handoff")
    review_url = f"/api/v1/growth/opportunities/{account.id}/review"
    handoff_url = f"/api/v1/growth/opportunities/{account.id}/crm-handoff"
    draft = client.post(
        f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json",
    ).data

    blocked = client.post(handoff_url, {"draft_id": draft["id"]}, format="json")
    assert blocked.status_code == 409
    assert blocked.data["message"] == "请先人工确认该机会为优先跟进。"

    client.post(review_url, {"decision": "PRIORITIZE"}, format="json")
    created = client.post(handoff_url, {"draft_id": draft["id"]}, format="json")
    duplicate = client.post(handoff_url, {"draft_id": draft["id"]}, format="json")

    assert created.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.data["id"] == created.data["id"]
    assert created.data["connector"] == "MOCK_CRM"
    assert created.data["delivery"] == "NEVER_SENT"
    assert created.data["payload_snapshot"]["candidate"]["name"] == "Evidence Buyer"
    assert created.data["payload_snapshot"]["source_evidence"][0] == {
        "url": signal.source_url,
        "content": signal.evidence_text,
        "content_hash": signal.content_hash,
        "source_type": "TENDER",
    }
    assert created.data["payload_snapshot"]["outreach_suggestion"]["english"]
    assert created.data["payload_snapshot"]["suggested_next_question"]


def test_low_evidence_can_be_reviewed_but_cannot_be_handed_off(opportunity):
    organization, account, signal = opportunity
    signal.confidence = 90
    signal.score_breakdown = {
        "icp_fit": 25,
        "intent_strength": 30,
        "recency": 20,
        "role_relevance": 15,
        "evidence_coverage": 5,
        "risk_penalty": 5,
    }
    signal.save(update_fields=["confidence", "score_breakdown", "updated_at"])
    client = _client(organization, suffix="low-evidence")
    client.post(
        f"/api/v1/growth/opportunities/{account.id}/review",
        {"decision": "PRIORITIZE"},
        format="json",
    )
    draft = client.post(
        f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json",
    ).data

    response = client.post(
        f"/api/v1/growth/opportunities/{account.id}/crm-handoff",
        {"draft_id": draft["id"]},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["message"] == "证据覆盖不足，暂时只能继续观察。"


def test_review_and_handoff_routes_are_documented(opportunity):
    organization, account, _signal = opportunity
    schema = _client(organization, suffix="schema").get("/api/v1/schema").json()

    assert "post" in schema["paths"]["/api/v1/growth/opportunities/{account_id}/review"]
    assert "post" in schema["paths"]["/api/v1/growth/opportunities/{account_id}/crm-handoff"]
