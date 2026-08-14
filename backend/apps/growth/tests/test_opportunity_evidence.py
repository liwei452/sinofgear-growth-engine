import hashlib

import pytest
from django.core.exceptions import ValidationError

from apps.growth.models import IntentSignal, TargetAccount
from apps.identity.models import Organization


@pytest.fixture
def opportunity_rows(db):
    organization = Organization.objects.create(
        name="Opportunity evidence", slug="opportunity-evidence",
    )
    account = TargetAccount.objects.create(
        organization=organization,
        name="Evidence Buyer",
        country="Germany",
        industry="Packaging machinery",
        is_demo=True,
    )
    return organization, account


def test_intent_signal_persists_a_versioned_score_that_matches_its_total(opportunity_rows):
    organization, account = opportunity_rows
    evidence = "Public page says the company is evaluating a new transmission line."
    signal = IntentSignal(
        organization=organization,
        account=account,
        signal_type="EXPANSION",
        source_label="Public company page",
        source_url="https://example.invalid/evidence",
        evidence_text=evidence,
        confidence=82,
        is_demo=True,
        collection_method="DEMO_FIXTURE",
        content_hash=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        score_breakdown={
            "icp_fit": 20,
            "intent_strength": 23,
            "recency": 14,
            "role_relevance": 10,
            "evidence_coverage": 17,
            "risk_penalty": 2,
        },
        scoring_rule_version="opportunity-v1",
        uncertainty_notes=["采购时间仍需人工确认"],
    )

    signal.full_clean()
    signal.save()

    saved = IntentSignal.objects.get(pk=signal.pk)
    assert saved.collection_method == "DEMO_FIXTURE"
    assert saved.content_hash == "759a0af750307d594872e49dd92e919c1b2178ee45fe7affa0a8516588cd254e"
    assert saved.score_breakdown["evidence_coverage"] == 17
    assert saved.scoring_rule_version == "opportunity-v1"
    assert saved.uncertainty_notes == ["采购时间仍需人工确认"]


@pytest.mark.parametrize(
    ("content_hash", "score_breakdown", "message"),
    [
        ("not-a-sha256", {
            "icp_fit": 20, "intent_strength": 23, "recency": 14,
            "role_relevance": 10, "evidence_coverage": 17, "risk_penalty": 2,
        }, "SHA-256"),
        ("a" * 64, {
            "icp_fit": 20, "intent_strength": 23, "recency": 14,
            "role_relevance": 10, "evidence_coverage": 17, "risk_penalty": 1,
        }, "total"),
    ],
)
def test_intent_signal_rejects_unverifiable_evidence_scoring(
    opportunity_rows, content_hash, score_breakdown, message,
):
    organization, account = opportunity_rows
    signal = IntentSignal(
        organization=organization,
        account=account,
        signal_type="EXPANSION",
        source_label="Public company page",
        source_url="https://example.invalid/evidence",
        evidence_text="Evidence",
        confidence=82,
        is_demo=True,
        collection_method="DEMO_FIXTURE",
        content_hash=content_hash,
        score_breakdown=score_breakdown,
        scoring_rule_version="opportunity-v1",
        uncertainty_notes=["采购时间仍需人工确认"],
    )

    with pytest.raises(ValidationError, match=message):
        signal.full_clean()
