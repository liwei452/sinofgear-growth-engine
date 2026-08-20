import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import (
    CandidateEnrichmentSnapshot,
    Contact,
    DiscoveryCandidate,
    FollowUp,
    IntentSignal,
    OutreachDraft,
    TargetAccount,
)
from apps.identity.models import Membership, Organization, Role


def _client(organization, *, reader=False, suffix="operator"):
    role = Role.objects.create_read_only() if reader else Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"candidate-enrichment-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Candidate enrichment", slug="candidate-enrichment")


def _candidate(organization, *, status=DiscoveryCandidate.Status.ACCEPTED, is_demo=False):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Jakarta Drives",
        country="Indonesia",
        website="https://jakarta.example.invalid/",
        industry="Industrial equipment",
        status=status,
        is_demo=is_demo,
        import_format="CSV",
        source_governance={
            "source_owner": "Licensed supplier",
            "license_contract": "Internal prospecting licence",
        },
        raw_record={},
        record_hash=("a" if status == DiscoveryCandidate.Status.ACCEPTED else "b") * 64,
    )


def test_accepted_candidate_gets_an_idempotent_fake_enrichment_preview_without_lead_creation(organization):
    candidate = _candidate(organization, is_demo=True)
    client = _client(organization)
    url = f"/api/v1/growth/enrichment/candidates/{candidate.id}/prepare"

    first = client.post(url, {}, format="json")
    repeated = client.post(url, {}, format="json")

    assert first.status_code == 201
    assert first.data == {
        "candidate_id": str(candidate.id),
        "mode": "FAKE_PREVIEW",
        "data_label": "Demo / Fake 资料补全预演",
        "facts": [
            {"field": "company_name", "value": "Jakarta Drives", "source": "许可名单导入"},
            {"field": "country", "value": "Indonesia", "source": "许可名单导入"},
            {"field": "industry", "value": "Industrial equipment", "source": "许可名单导入"},
            {"field": "website", "value": "https://jakarta.example.invalid/", "source": "许可名单导入"},
        ],
        "public_contact_paths": [],
        "uncertainties": ["尚未联网核实公司官网", "尚未发现可验证的公开联系页面", "没有采购意向证据"],
        "message": "已生成资料补全预演；没有联网抓取，也不会联系客户。",
        "created": True,
        "account_id": None,
    }
    assert repeated.status_code == 200
    assert repeated.data["created"] is False
    summary = client.get("/api/v1/growth/discovery/profile")
    queued = summary.data["enrichment_candidates"]
    assert len(queued) == 1
    assert queued[0]["company_name"] == "Jakarta Drives"
    assert queued[0]["latest_preview"] == {
        "candidate_id": str(candidate.id),
        "mode": "FAKE_PREVIEW",
        "data_label": "Demo / Fake 资料补全预演",
        "facts": first.data["facts"],
        "public_contact_paths": [],
        "uncertainties": first.data["uncertainties"],
        "message": "已生成资料补全预演；没有联网抓取，也不会联系客户。",
        "created": False,
        "account_id": None,
    }
    assert CandidateEnrichmentSnapshot.objects.filter(organization=organization).count() == 1
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    assert Contact.objects.filter(organization=organization).count() == 0
    assert IntentSignal.objects.filter(organization=organization).count() == 0


def test_formal_candidate_prepares_only_imported_facts_for_human_confirmation(organization):
    candidate = _candidate(organization)
    client = _client(organization, suffix="formal")

    response = client.post(
        f"/api/v1/growth/enrichment/candidates/{candidate.id}/prepare", {}, format="json",
    )

    assert response.status_code == 201
    assert response.data["mode"] == "IMPORTED_FACTS_REVIEW"
    assert response.data["data_label"] == "许可名单事实 · 待人工确认"
    assert response.data["facts"] == [
        {"field": "company_name", "value": "Jakarta Drives", "source": "许可名单导入"},
        {"field": "country", "value": "Indonesia", "source": "许可名单导入"},
        {"field": "industry", "value": "Industrial equipment", "source": "许可名单导入"},
        {"field": "website", "value": "https://jakarta.example.invalid/", "source": "许可名单导入"},
    ]
    assert response.data["public_contact_paths"] == []
    assert "采购意向" in response.data["message"]
    snapshot = CandidateEnrichmentSnapshot.objects.get(candidate=candidate)
    assert snapshot.evidence_envelope["connector"] == "USER_IMPORTED_FACTS"
    assert snapshot.evidence_envelope["network_access"] is False


def test_formal_candidate_replaces_a_stale_fake_preview_without_reupload(organization):
    candidate = _candidate(organization)
    CandidateEnrichmentSnapshot.objects.create(
        organization=organization,
        candidate=candidate,
        mode="FAKE_PREVIEW",
        facts=[{"field": "industry", "value": "Imagined", "source": "Demo"}],
        evidence_envelope={"connector": "FAKE_WEBSITE_ENRICHMENT"},
    )
    client = _client(organization, suffix="stale")

    response = client.post(
        f"/api/v1/growth/enrichment/candidates/{candidate.id}/prepare", {}, format="json",
    )

    assert response.status_code == 200
    assert response.data["mode"] == "IMPORTED_FACTS_REVIEW"
    assert response.data["facts"][0]["value"] == "Jakarta Drives"
    snapshot = CandidateEnrichmentSnapshot.objects.get(candidate=candidate)
    assert snapshot.mode == "IMPORTED_FACTS_REVIEW"
    assert snapshot.evidence_envelope["connector"] == "USER_IMPORTED_FACTS"


def test_enrichment_requires_accepted_tenant_candidate_and_manage_permission(organization):
    pending = _candidate(organization, status=DiscoveryCandidate.Status.PENDING_REVIEW)
    operator = _client(organization, suffix="pending")
    reader = _client(organization, reader=True, suffix="reader")
    other = Organization.objects.create(name="Other enrichment", slug="other-enrichment")
    other_operator = _client(other, suffix="other")
    url = f"/api/v1/growth/enrichment/candidates/{pending.id}/prepare"

    blocked = operator.post(url, {}, format="json")
    forbidden = reader.post(url, {}, format="json")
    hidden = other_operator.post(url, {}, format="json")

    assert blocked.status_code == 409
    assert blocked.data["code"] == "CANDIDATE_REVIEW_REQUIRED"
    assert forbidden.status_code == 403
    assert hidden.status_code == 404


def test_prepared_candidate_can_be_added_to_follow_up_without_inventing_intent(organization):
    candidate = _candidate(organization)
    client = _client(organization, suffix="promote")
    prepared = client.post(
        f"/api/v1/growth/enrichment/candidates/{candidate.id}/prepare", {}, format="json",
    )
    assert prepared.status_code == 201

    url = f"/api/v1/growth/enrichment/candidates/{candidate.id}/follow-up"
    first = client.post(url, {}, format="json")
    repeated = client.post(url, {}, format="json")

    assert first.status_code == 201
    assert first.data["status"] == "OPEN"
    assert first.data["created"] is True
    assert first.data["message"] == "已加入人工跟进；没有生成采购意向，也没有联系客户。"
    assert repeated.status_code == 200
    assert repeated.data["account_id"] == first.data["account_id"]
    assert repeated.data["created"] is False
    account = TargetAccount.objects.get(id=first.data["account_id"])
    assert account.name == "Jakarta Drives"
    assert account.source_identity == f"candidate:{candidate.id}"
    assert FollowUp.objects.filter(organization=organization, account=account).count() == 1
    assert Contact.objects.filter(organization=organization, account=account).count() == 0
    assert IntentSignal.objects.filter(organization=organization, account=account).count() == 0

    draft = client.post(f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json")
    repeated_draft = client.post(
        f"/api/v1/growth/opportunities/{account.id}/draft", {}, format="json",
    )
    assert draft.status_code == 201
    assert repeated_draft.status_code == 200
    assert repeated_draft.data["id"] == draft.data["id"]
    assert OutreachDraft.objects.filter(organization=organization, account=account).count() == 1
    assert draft.data["delivery"] == "NEVER_SENT"
    assert "Jakarta Drives" in draft.data["English draft"]


def test_pending_candidate_list_license_blocks_follow_up_and_contact_draft(organization):
    candidate = _candidate(organization)
    candidate.source_governance["license_contract"] = "待人工确认使用范围"
    candidate.save(update_fields=["source_governance", "updated_at"])
    client = _client(organization, suffix="pending-license")
    client.post(f"/api/v1/growth/enrichment/candidates/{candidate.id}/prepare", {}, format="json")

    follow_up = client.post(f"/api/v1/growth/enrichment/candidates/{candidate.id}/follow-up", {}, format="json")

    assert follow_up.status_code == 409
    assert follow_up.data["code"] == "CANDIDATE_LICENSE_CONFIRMATION_REQUIRED"
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    assert FollowUp.objects.filter(organization=organization).count() == 0


def test_discovery_profile_preserves_minimum_workflow_read_model_without_evidence_contract(organization):
    candidate = _candidate(organization)
    snapshot = CandidateEnrichmentSnapshot.objects.create(
        organization=organization,
        candidate=candidate,
        mode="WEBSITE_PUBLIC",
        evidence_envelope={"source_url": "https://jakarta.example.invalid/evidence"},
    )
    client = _client(organization, suffix="summary-boundary")
    follow_up = client.post(f"/api/v1/growth/enrichment/candidates/{candidate.id}/follow-up", {}, format="json")
    assert follow_up.status_code == 201
    snapshot.refresh_from_db()

    summary = client.get("/api/v1/growth/discovery/profile")

    item = summary.data["enrichment_candidates"][0]
    assert item["workflow"] == {
        "account_id": follow_up.data["account_id"],
        "follow_up_status": "OPEN",
        "draft": None,
    }
    assert "evidence_links" not in item
