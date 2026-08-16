import pytest

from apps.growth.lead_intent import intent_score_from_visits, record_lead_visit
from apps.growth.models import DiscoveryCandidate
from apps.identity.models import Organization


def test_intent_score_accumulates_website_signals():
    paths = [
        "/replacement-gears/",
        "/reverse-engineering-gears/",
        "/quality/",
        "/products/spur-gears",
        "/products/helical-gears",
    ]
    score, breakdown = intent_score_from_visits(paths, email_clicked=True, sessions=2)
    assert breakdown["email_click"] == 5
    assert breakdown["return_visit"] == 8
    assert breakdown["multi_product"] == 5
    assert score == 5 + 8 + 5 + (8 + 10 + 5 + 5 + 5)


def test_intent_score_deduplicates_repeated_pages_and_caps_at_100():
    paths = [
        "/replacement-gears/",
        "/replacement-gears/",
        "/replacement-gears/",
    ]
    score, breakdown = intent_score_from_visits(paths, sessions=1)
    assert score == 8
    assert breakdown["page_signals"] == 8

    score_capped, _ = intent_score_from_visits(
        ["/reverse-engineering-gears/"] * 20,
        email_clicked=True,
        sessions=10,
    )
    assert score_capped <= 100


def test_intent_score_is_zero_without_signals():
    score, breakdown = intent_score_from_visits([], sessions=1)
    assert score == 0
    assert breakdown == {
        "email_click": 0,
        "page_signals": 0,
        "return_visit": 0,
        "multi_product": 0,
    }


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Lead intent", slug="lead-intent")


def test_record_lead_visit_updates_candidate_intent_score(organization):
    candidate = DiscoveryCandidate.objects.create(
        organization=organization,
        company_name="ABC Mining",
        country="ZAF",
        import_format="GOOGLE_MAPS",
        record_hash="visit-test-hash",
    )
    record_lead_visit(lead_id=candidate.id, path="/replacement-gears/", session_id="s1")
    record_lead_visit(lead_id=candidate.id, path="/reverse-engineering-gears/", session_id="s2")

    candidate.refresh_from_db()
    assert candidate.intent_score == 8 + 10 + 8  # two page signals + return visit
    assert candidate.intent_breakdown["return_visit"] == 8
