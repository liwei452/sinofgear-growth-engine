from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.growth.models import (
    AccountFunnelEvent,
    IntentSignal,
    OutreachDraft,
    ReactivationRecord,
    TargetAccount,
)
from apps.identity.models import Membership, Organization, Role


@pytest.fixture
def operator_client(db):
    organization = Organization.objects.create(name="Reactivation org", slug="reactivation-org")
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(username="reactivation-operator", password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client, organization


def account_with_signal(organization, *, name, confidence, coverage, is_demo=True):
    account = TargetAccount.objects.create(
        organization=organization,
        name=name,
        country="Germany",
        industry="Packaging machinery",
        is_demo=is_demo,
    )
    evidence = f"Verified public signal for {name}"
    IntentSignal.objects.create(
        organization=organization,
        account=account,
        signal_type="PRODUCT_CHANGE",
        source_label="Saved public company page",
        source_url="https://example.invalid/saved-evidence",
        evidence_text=evidence,
        confidence=confidence,
        is_demo=is_demo,
        collection_method="DEMO_FIXTURE" if is_demo else "MANUAL_URL",
        content_hash=("a" if name.startswith("Pack") else "b") * 64,
        score_breakdown={
            "icp_fit": 20,
            "intent_strength": max(confidence - 20 - 14 - 12 - coverage, 0),
            "recency": 14,
            "role_relevance": 12,
            "evidence_coverage": coverage,
            "risk_penalty": 0,
        },
        uncertainty_notes=["Purchase timing is not confirmed"],
    )
    return account


@pytest.mark.django_db
def test_legal_existing_relationship_can_create_and_approve_a_never_sent_draft(operator_client):
    client, organization = operator_client
    account = account_with_signal(
        organization, name="PackTech GmbH", confidence=88, coverage=18,
    )
    selected = client.post("/api/v1/growth/reactivations", {
        "account_id": str(account.id),
        "relationship_source": "PAST_INQUIRY",
        "last_interacted_at": (timezone.now() - timedelta(days=120)).isoformat(),
        "interaction_summary": "Discussed a gear drawing review at the 2025 trade fair; no order was claimed.",
        "relationship_confirmed": True,
    }, format="json")

    assert selected.status_code == 201
    assert selected.data["tier"] == "STRATEGIC"
    assert selected.data["is_demo"] is True
    assert selected.data["recommended_action"] == "Prepare a human-reviewed reactivation draft"
    assert selected.data["delivery"] == "NEVER_SENT"

    drafted = client.post(f"/api/v1/growth/reactivations/{selected.data['id']}/draft", {}, format="json")
    approved = client.post(f"/api/v1/growth/reactivations/{selected.data['id']}/approve", {}, format="json")

    assert drafted.status_code == 201
    assert "PackTech GmbH" in drafted.data["english_draft"]
    assert "2025 trade fair" in drafted.data["english_draft"]
    assert "Packaging machinery" in drafted.data["english_draft"]
    assert "purchase" not in drafted.data["english_draft"].lower()
    assert drafted.data["delivery"] == "NEVER_SENT"
    assert approved.status_code == 200
    assert approved.data == {
        "id": selected.data["id"],
        "status": "APPROVED",
        "draft_status": "APPROVED",
        "delivery": "NEVER_SENT",
        "message": "Draft approved for future manual sending; nothing was sent.",
    }
    assert OutreachDraft.objects.get(id=drafted.data["draft_id"]).status == OutreachDraft.Status.APPROVED
    reactivation = ReactivationRecord.objects.get(organization=organization)
    assert reactivation.status == ReactivationRecord.Status.APPROVED
    assert [event.event_type for event in reactivation.events.all()] == [
        AccountFunnelEvent.EventType.REACTIVATION_SELECTED,
        AccountFunnelEvent.EventType.REACTIVATION_DRAFTED,
        AccountFunnelEvent.EventType.REACTIVATION_APPROVED,
    ]


@pytest.mark.django_db
def test_unconfirmed_relationship_is_rejected_and_observation_account_cannot_generate_draft(operator_client):
    client, organization = operator_client
    account = account_with_signal(
        organization, name="NordMotion AB", confidence=52, coverage=12,
    )
    payload = {
        "account_id": str(account.id),
        "relationship_source": "OWNED_CRM",
        "last_interacted_at": (timezone.now() - timedelta(days=200)).isoformat(),
        "interaction_summary": "Imported from our own historical CRM with a recorded prior conversation.",
        "relationship_confirmed": False,
    }

    rejected = client.post("/api/v1/growth/reactivations", payload, format="json")
    assert rejected.status_code == 400
    assert rejected.data["code"] == "LEGAL_RELATIONSHIP_REQUIRED"

    payload["relationship_confirmed"] = True
    selected = client.post("/api/v1/growth/reactivations", payload, format="json")
    blocked = client.post(f"/api/v1/growth/reactivations/{selected.data['id']}/draft", {}, format="json")

    assert selected.status_code == 201
    assert selected.data["tier"] == "OBSERVATION"
    assert selected.data["recommended_action"] == "Complete account evidence before outreach"
    assert blocked.status_code == 409
    assert blocked.data["code"] == "REACTIVATION_EVIDENCE_INSUFFICIENT"
    assert OutreachDraft.objects.filter(organization=organization, account=account).count() == 0


@pytest.mark.django_db
def test_reactivation_never_exposes_or_mutates_another_organization(operator_client):
    client, _organization = operator_client
    foreign = Organization.objects.create(name="Foreign", slug="foreign-reactivation")
    account = TargetAccount.objects.create(
        organization=foreign, name="Foreign secret", country="US",
    )

    response = client.post("/api/v1/growth/reactivations", {
        "account_id": str(account.id),
        "relationship_source": "EXISTING_CUSTOMER",
        "last_interacted_at": (timezone.now() - timedelta(days=90)).isoformat(),
        "interaction_summary": "Existing customer relationship in foreign tenant.",
        "relationship_confirmed": True,
    }, format="json")

    assert response.status_code == 404
    assert b"Foreign secret" not in response.content


@pytest.mark.django_db
def test_unreviewed_non_demo_signal_cannot_unlock_reactivation_outreach(operator_client):
    client, organization = operator_client
    account = account_with_signal(
        organization, name="Licensed Buyer", confidence=88, coverage=18, is_demo=False,
    )

    selected = client.post("/api/v1/growth/reactivations", {
        "account_id": str(account.id),
        "relationship_source": "EXISTING_CUSTOMER",
        "last_interacted_at": (timezone.now() - timedelta(days=90)).isoformat(),
        "interaction_summary": "Existing customer in our ERP; recent web signal has not been reviewed.",
        "relationship_confirmed": True,
    }, format="json")

    assert selected.status_code == 201
    assert selected.data["tier"] == "OBSERVATION"
    blocked = client.post(f"/api/v1/growth/reactivations/{selected.data['id']}/draft", {}, format="json")
    assert blocked.status_code == 409
