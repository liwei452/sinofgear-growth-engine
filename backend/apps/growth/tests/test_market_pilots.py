import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.market_pilots import market_pilot_summary, validate_company_evidence_source
from apps.growth.market_pilots import market_profiles_for
from apps.growth.models import MarketCountryProfile
from apps.identity.models import Organization
from apps.identity.models import Membership, Role


@pytest.mark.django_db
def test_market_pilot_summary_keeps_two_active_routes_and_two_quality_gates():
    summary = market_pilot_summary(signals=[], accounts=[])

    assert [(market["country_code"], market["status"], market["route"]) for market in summary["markets"][:5]] == [
        ("IDN", "ACTIVE_MARKET", "STRONG_CUSTOMS_DATA"),
        ("ZAF", "ACTIVE_MARKET", "MIXED_SIGNALS"),
        ("CHL", "DATA_VALIDATION", "TRADE_TENDER_WEB"),
        ("VNM", "DATA_VALIDATION", "SECOND_PHASE"),
        ("PHL", "DATA_VALIDATION", "SECOND_PHASE"),
    ]
    assert len(summary["markets"]) == 21
    assert summary["score_weights"] == {
        "data_availability": 25,
        "demand_strength": 25,
        "purchase_intent": 20,
        "company_reachability": 15,
        "commercial_execution": 15,
    }
    assert summary["quality_gate"] == {
        "minimum_raw_samples": 200,
        "minimum_named_buyer_rate": 80,
        "minimum_active_entity_match_rate": 70,
        "maximum_median_record_age_days": 90,
        "maximum_duplicate_rate": 10,
        "license_required": True,
    }
    assert summary["search_policy"]["hs_codes"] == ["848340", "848390"]
    assert "gear shaft" in summary["search_policy"]["include_terms"]
    assert "complete gearbox" in summary["search_policy"]["exclude_terms"]
    for market in summary["markets"][:2]:
        assert market["metrics"] == {
            "effective_customer_rate": None,
            "positive_reply_rate": None,
            "source_cost_micros": 0,
            "raw_sample_count": 0,
        }
    chile = next(market for market in summary["markets"] if market["country_code"] == "CHL")
    assert chile["recommended_wave"] == "下一优先"
    assert chile["recommendation_reasons"]
    assert chile["sample_quality"]["evidence_company_threshold"] == 20
    india = next(market for market in summary["markets"] if market["country_code"] == "IND")
    assert india["source_types"] == ["TENDER", "COMPANY_WEB"]
    assert "DIRECT_CUSTOMS" not in india["source_types"]
    assert any("授权" in reason for reason in india["hold_reasons"])
    assert summary["validation_goals"] == {
        "reviewed_valid_companies": 50,
        "sales_conversations": 15,
        "positive_intent_signals": 5,
        "progressed_opportunities": 2,
        "weeks": 8,
    }


def test_market_workbench_has_required_regions_routes_and_explainable_demo_metadata():
    summary = market_pilot_summary(signals=[], accounts=[])
    markets = {market["country_code"]: market for market in summary["markets"]}

    assert {"USA", "GBR", "CAN", "VNM", "IDN", "PHL", "ZAF", "EGY", "KEN", "NGA", "MAR"} <= set(markets)
    assert {market["path_family"] for market in markets.values()} == {"CUSTOMS_STRONG", "MIXED_ACQUISITION"}
    for code in ["USA", "GBR", "CAN", "VNM", "IDN", "PHL", "ZAF", "EGY", "KEN", "NGA", "MAR"]:
        market = markets[code]
        assert market["region"]
        assert market["suitable_industries"]
        assert market["data_availability_label"]
        assert market["evidence_note"]
        assert market["recommended_action"]
        assert market["recommendation_reasons"]
        assert market["hold_reasons"]
        assert market["is_demo"] is True
        assert market["is_watched"] is False


@pytest.mark.django_db
def test_operator_can_watch_a_market_for_only_their_organization_and_refresh_keeps_it():
    organization = Organization.objects.create(name="Market watcher", slug="market-watcher")
    other = Organization.objects.create(name="Other watcher", slug="other-watcher")
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(username="market-watch-operator", password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    market_profiles_for(organization)
    market_profiles_for(other)

    watched = client.post("/api/v1/growth/markets/USA/watch", {}, format="json")
    workspace = client.get("/api/v1/growth/workspace")

    assert watched.status_code == 200
    assert watched.data == {"country_code": "USA", "is_watched": True, "message": "已加入观察市场。"}
    usa = next(market for market in workspace.data["market_pilots"]["markets"] if market["country_code"] == "USA")
    assert usa["is_watched"] is True
    assert MarketCountryProfile.objects.get(organization=other, country_code="USA").is_watched is False


def test_aggregate_trade_cannot_be_presented_as_company_purchase_evidence():
    with pytest.raises(ValueError, match="market context only"):
        validate_company_evidence_source("AGGREGATE_TRADE")

    validate_company_evidence_source("DIRECT_CUSTOMS")
    validate_company_evidence_source("TENDER")


@pytest.mark.django_db
def test_market_radar_profiles_are_persistent_and_can_move_through_five_stages():
    organization = Organization.objects.create(name="Market radar", slug="market-radar")

    profiles = market_profiles_for(organization)

    assert len(profiles) == 21
    chile = MarketCountryProfile.objects.get(organization=organization, country_code="CHL")
    assert chile.status == "DATA_VALIDATION"
    chile.status = "SMALL_PILOT"
    chile.save(update_fields=["status", "updated_at"])
    assert market_profiles_for(organization)[2].status == "SMALL_PILOT"
