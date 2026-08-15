from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import DiscoveryProfile, IntentSignal
from apps.identity.models import Membership, Organization, Role
from integrations.sources.base import SourceBatch, SourceItem


RUN_URL = "/api/v1/growth/discovery/run"
PROFILE_URL = "/api/v1/growth/discovery/profile"


class FakeSource:
    def fetch(self, query):
        return SourceBatch(
            items=(SourceItem(
                external_id="534032-2026",
                buyer_name="API Contracting Authority",
                buyer_country="DEU",
                title="Industrial gears",
                published_at=datetime(2026, 8, 3, tzinfo=dt_timezone.utc),
                deadline_at=datetime(2026, 9, 8, tzinfo=dt_timezone.utc),
                source_url="https://ted.europa.eu/en/notice/-/detail/534032-2026",
                cpv_codes=("42141300",),
            ),),
            capability_snapshot={
                "source": "TED", "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "ANONYMOUS", "result_limit": query.limit,
            },
            total_count=1,
        )


def _client(organization, *, reader=False, suffix="manager"):
    role = Role.objects.create_read_only() if reader else Role.objects.create_operator()
    user = get_user_model().objects.create_user(
        username=f"discovery-api-{suffix}", password="password",
    )
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Discovery API", slug="discovery-api")


def test_workspace_exposes_an_owner_friendly_discovery_summary(organization):
    summary = _client(organization).get("/api/v1/growth/workspace").data["discovery"]

    assert summary == {
        "enabled": True,
        "source_label": "欧盟官方采购数据",
        "schedule_label": "每天自动查找",
        "product_scope_label": "齿轮、传动与驱动部件",
        "next_run_at": None,
        "last_run": None,
        "available_sources": [
            {"code": "TED", "label": "欧盟官方采购数据", "status": "ACTIVE"},
            {"code": "GOOGLE_PLACES", "label": "Google Maps 官方企业发现", "status": "KEY_REQUIRED"},
        ],
    }
    assert "cursor" not in summary
    assert DiscoveryProfile.objects.filter(organization=organization).count() == 1


def test_manager_runs_official_discovery_while_reader_is_forbidden(organization, monkeypatch):
    monkeypatch.setattr("apps.growth.discovery.build_discovery_source", FakeSource)

    response = _client(organization).post(RUN_URL, {}, format="json")
    reader_response = _client(organization, reader=True, suffix="reader").post(
        RUN_URL, {}, format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == "SUCCEEDED"
    assert response.data["new_company_count"] == 1
    assert response.data["new_signal_count"] == 1
    assert response.data["message"] == "发现 1 条新采购信号，等待你审核。"
    assert reader_response.status_code == 403
    assert IntentSignal.objects.get().collection_method == "OFFICIAL_PUBLIC_API"


def test_manager_can_pause_daily_discovery(organization):
    response = _client(organization).patch(PROFILE_URL, {"enabled": False}, format="json")

    assert response.status_code == 200
    assert response.data["enabled"] is False
    assert response.data["schedule_label"] == "已暂停自动查找"
    assert DiscoveryProfile.objects.get(organization=organization).enabled is False


def test_discovery_routes_are_documented(organization):
    schema = _client(organization, suffix="schema").get("/api/v1/schema").json()

    assert set(schema["paths"][RUN_URL]) == {"post"}
    assert set(schema["paths"][PROFILE_URL]) == {"patch"}
