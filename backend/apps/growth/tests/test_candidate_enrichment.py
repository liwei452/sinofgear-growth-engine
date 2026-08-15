import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import (
    CandidateEnrichmentSnapshot,
    Contact,
    DiscoveryCandidate,
    IntentSignal,
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


def _candidate(organization, *, status=DiscoveryCandidate.Status.ACCEPTED):
    return DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="Jakarta Drives",
        country="Indonesia",
        website="https://jakarta.example.invalid/",
        industry="Industrial equipment",
        status=status,
        import_format="CSV",
        source_governance={
            "source_owner": "Licensed supplier",
            "license_contract": "Internal prospecting licence",
        },
        raw_record={},
        record_hash=("a" if status == DiscoveryCandidate.Status.ACCEPTED else "b") * 64,
    )


def test_accepted_candidate_gets_an_idempotent_fake_enrichment_preview_without_lead_creation(organization):
    candidate = _candidate(organization)
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
    }
    assert repeated.status_code == 200
    assert repeated.data["created"] is False
    workspace = client.get("/api/v1/growth/workspace")
    queued = workspace.data["discovery"]["enrichment_candidates"]
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
    }
    assert CandidateEnrichmentSnapshot.objects.filter(organization=organization).count() == 1
    assert TargetAccount.objects.filter(organization=organization).count() == 0
    assert Contact.objects.filter(organization=organization).count() == 0
    assert IntentSignal.objects.filter(organization=organization).count() == 0


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
