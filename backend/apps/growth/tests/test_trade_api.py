from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from apps.growth.models import TargetAccount, TradeDatasetSnapshot, TradeSyncRun
from apps.growth.trade_contracts import (
    EnterpriseTradeRecord,
    PartyRole,
    TradeParty,
    validate_enterprise_trade_record,
)
from apps.identity.models import Membership, Organization, Role
from integrations.sources.base import SourceAdapterError


SYNC_URL = "/api/v1/growth/trade-syncs"
SNAPSHOTS_URL = "/api/v1/growth/trade-snapshots"
INDICATORS_URL = "/api/v1/growth/trade-indicators"


def _client(organization, *, reader=False, suffix="manager"):
    role = Role.objects.create_read_only() if reader else Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"trade-api-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Trade API", slug="trade-api")


def _payload(**overrides):
    return {
        "country_code": "IDN",
        "hs_codes": ["848340", "848390"],
        "periods": ["2023", "2024"],
        **overrides,
    }


def test_trade_sync_is_disabled_by_default_and_never_silently_fakes_data(organization):
    response = _client(organization).post(SYNC_URL, _payload(), format="json")

    assert response.status_code == 503
    assert response.data == {
        "code": "CONFIGURATION_REQUIRED",
        "message": "公开贸易数据源尚未启用。",
        "recovery_action": "由管理员明确启用官方公共数据连接器；当前不会自动加载演示数据。",
    }
    assert TradeSyncRun.objects.filter(organization=organization).count() == 0
    assert TradeDatasetSnapshot.objects.filter(organization=organization).count() == 0


@override_settings(PUBLIC_TRADE_PROVIDER_MODE="FIXTURE")
def test_fixture_sync_is_explicit_idempotent_and_does_not_create_target_accounts(organization):
    client = _client(organization)

    first = client.post(SYNC_URL, _payload(), format="json")
    second = client.post(SYNC_URL, _payload(), format="json")

    assert first.status_code == 201
    assert first.data["mode"] == "FIXTURE"
    assert first.data["is_demo"] is True
    assert first.data["scope_warning"] == "宏观贸易仅用于市场判断，不是具体买家证据。"
    assert second.status_code == 200
    assert second.data["snapshot_ids"] == first.data["snapshot_ids"]
    assert TradeDatasetSnapshot.objects.filter(organization=organization).count() == 6
    assert TradeDatasetSnapshot.objects.filter(organization=organization, is_demo=True).count() == 6
    assert TargetAccount.objects.filter(organization=organization).count() == 0


@override_settings(PUBLIC_TRADE_PROVIDER_MODE="FIXTURE")
def test_reader_can_view_trade_evidence_but_cannot_trigger_sync(organization):
    manager = _client(organization)
    manager.post(SYNC_URL, _payload(), format="json")
    reader = _client(organization, reader=True, suffix="reader")

    sync_response = reader.post(SYNC_URL, _payload(), format="json")
    snapshots = reader.get(SNAPSHOTS_URL, {"country_code": "IDN", "hs_code": "848340"})

    assert sync_response.status_code == 403
    assert snapshots.status_code == 200
    assert snapshots.data["count"] == 3
    assert all(item["is_demo"] is True for item in snapshots.data["results"])
    assert all(item["source_url"].startswith("https://comtradeplus.un.org/") for item in snapshots.data["results"])
    assert all(item["provenance"]["not_company_evidence"] is True for item in snapshots.data["results"])


@override_settings(PUBLIC_TRADE_PROVIDER_MODE="FIXTURE")
def test_indicators_return_formula_inputs_and_source_records(organization):
    client = _client(organization)
    client.post(SYNC_URL, _payload(), format="json")

    response = client.get(INDICATORS_URL, {
        "country_code": "IDN",
        "hs_code": ["848340", "848390"],
        "period": ["2023", "2024"],
    })

    assert response.status_code == 200
    assert response.data["status"] == "READY"
    assert response.data["is_demo"] is True
    assert response.data["indicators"]["year_over_year"]["formula"] == (
        "(current - previous) / previous * 100"
    )
    assert response.data["indicators"]["year_over_year"]["inputs"] == {
        "current": "225000.00", "previous": "180000.00",
    }
    assert response.data["indicators"]["china_share"]["inputs"] == {
        "china_value": "90000.00", "world_value": "225000.00",
    }
    assert len(response.data["evidence"]) == 6


@override_settings(PUBLIC_TRADE_PROVIDER_MODE="FIXTURE")
def test_trade_api_rejects_unknown_fields_bad_hs_and_unknown_country(organization):
    client = _client(organization)

    unknown = client.post(SYNC_URL, _payload(secret="must-not-pass"), format="json")
    bad_hs = client.post(SYNC_URL, _payload(hs_codes=["84834X"]), format="json")
    bad_country = client.post(SYNC_URL, _payload(country_code="ZZZ"), format="json")

    assert unknown.status_code == 400
    assert unknown.data["unknown_fields"] == ["secret"]
    assert bad_hs.status_code == 400
    assert "hs_codes" in bad_hs.data
    assert bad_country.status_code == 400
    assert "country_code" in bad_country.data


@override_settings(PUBLIC_TRADE_PROVIDER_MODE="FIXTURE")
def test_trade_snapshots_are_cross_organization_isolated(organization):
    first_client = _client(organization)
    first_client.post(SYNC_URL, _payload(), format="json")
    other = Organization.objects.create(name="Other trade API", slug="other-trade-api")
    other_client = _client(other, suffix="other")

    snapshots = other_client.get(SNAPSHOTS_URL, {"country_code": "IDN"})
    indicators = other_client.get(INDICATORS_URL, {
        "country_code": "IDN", "hs_code": "848340", "period": ["2023", "2024"],
    })

    assert snapshots.data == {"count": 0, "results": []}
    assert indicators.data["status"] == "NO_DATA"
    assert indicators.data["evidence"] == []


def test_trade_sync_failure_is_safe_and_audited(organization, monkeypatch):
    class FailingSource:
        source_code = "UN_COMTRADE"

        def fetch(self, query):
            raise SourceAdapterError("SOURCE_RATE_LIMITED")

    monkeypatch.setattr(
        "apps.growth.views.trade_source_runtime",
        lambda: (FailingSource(), "OFFICIAL_PUBLIC"),
    )

    response = _client(organization).post(SYNC_URL, _payload(), format="json")

    assert response.status_code == 502
    assert response.data == {
        "code": "SOURCE_RATE_LIMITED",
        "message": "官方公开贸易数据同步失败。",
        "recovery_action": "稍后重试；系统没有创建买家公司或采购意向。",
    }
    run = TradeSyncRun.objects.get(organization=organization)
    assert run.status == TradeSyncRun.Status.FAILED
    assert run.error_code == "SOURCE_RATE_LIMITED"
    assert TradeDatasetSnapshot.objects.filter(organization=organization).count() == 0


def test_trade_routes_are_documented(organization):
    schema = _client(organization, suffix="schema").get("/api/v1/schema").json()

    assert set(schema["paths"][SYNC_URL]) == {"post"}
    assert set(schema["paths"][SNAPSHOTS_URL]) == {"get"}
    assert set(schema["paths"][INDICATORS_URL]) == {"get"}


def test_enterprise_trade_contract_requires_licensed_party_roles_and_normalization():
    record = EnterpriseTradeRecord(
        external_record_id="bol-2026-001",
        shipment_date=date(2026, 7, 1),
        hs_code="848340",
        parties=(
            TradeParty(
                role=PartyRole.IMPORTER,
                raw_name="Example Mining Ltd.",
                normalized_name="EXAMPLE MINING LTD",
                country_code="ZAF",
                entity_match_confidence=91,
                freight_forwarder_review=False,
            ),
            TradeParty(
                role=PartyRole.NOTIFY_PARTY,
                raw_name="Example Logistics",
                normalized_name="EXAMPLE LOGISTICS",
                country_code="ZAF",
                entity_match_confidence=72,
                freight_forwarder_review=True,
            ),
        ),
        source_owner="Licensed shipment provider",
        license_contract="contract-2026-01",
        allowed_fields=("importer", "notify_party", "hs_code", "shipment_date"),
        retention_days=365,
        redistribution_allowed=False,
        source_url="https://provider.example.invalid/records/bol-2026-001",
    )

    validated = validate_enterprise_trade_record(record)

    assert {party.role for party in validated.parties} == {
        PartyRole.IMPORTER, PartyRole.NOTIFY_PARTY,
    }
    assert validated.parties[1].freight_forwarder_review is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"license_contract": ""}, "license"),
        ({"source_owner": ""}, "source owner"),
        ({"allowed_fields": ()}, "allowed fields"),
        ({"retention_days": 0}, "retention"),
        ({"parties": ()}, "party"),
    ],
)
def test_enterprise_trade_contract_rejects_unlicensed_or_incomplete_records(overrides, message):
    values = {
        "external_record_id": "bol-2026-001",
        "shipment_date": date(2026, 7, 1),
        "hs_code": "848340",
        "parties": (TradeParty(
            role=PartyRole.CONSIGNEE,
            raw_name="Example Works",
            normalized_name="EXAMPLE WORKS",
            country_code="IDN",
            entity_match_confidence=85,
            freight_forwarder_review=False,
        ),),
        "source_owner": "Licensed provider",
        "license_contract": "contract-2026-01",
        "allowed_fields": ("consignee", "hs_code"),
        "retention_days": 365,
        "redistribution_allowed": False,
        "source_url": "https://provider.example.invalid/records/bol-2026-001",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=f"(?i){message}"):
        validate_enterprise_trade_record(EnterpriseTradeRecord(**values))
