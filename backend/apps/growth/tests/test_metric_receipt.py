from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import MetricReceipt
from apps.identity.models import Membership, Organization, Role


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Metrics", slug="metrics")


@pytest.fixture
def client(organization):
    user = get_user_model().objects.create_user(username="metric-operator", password="pw")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    api = APIClient()
    assert api.login(username="metric-operator", password="pw")
    return api


def _payload(**overrides):
    payload = {
        "channel": "LINKEDIN",
        "is_demo": False,
        "payload": {
            "views": 10,
            "clicks": 3,
            "replies": 1,
            "inquiries": 2,
            "source_note": "平台后台核实",
            "observed_at": datetime(2026, 8, 18, tzinfo=timezone.utc).isoformat(),
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_metric_receipt_rejects_unknown_channel(client):
    response = client.post(
        "/api/v1/growth/metric-receipts",
        _payload(channel="PINTEREST"),
        format="json",
    )
    assert response.status_code == 400
    assert MetricReceipt.objects.count() == 0


@pytest.mark.django_db
def test_metric_receipt_rejects_negative_number(client):
    response = client.post(
        "/api/v1/growth/metric-receipts",
        _payload(),
        format="json",
    )
    response = client.post(
        "/api/v1/growth/metric-receipts",
        _payload(payload={
            "views": -1,
            "source_note": "平台后台核实",
            "observed_at": datetime(2026, 8, 18, tzinfo=timezone.utc).isoformat(),
        }),
        format="json",
    )
    assert response.status_code == 400
    assert MetricReceipt.objects.count() == 1


@pytest.mark.django_db
def test_metric_receipt_accepts_valid_payload(client):
    response = client.post(
        "/api/v1/growth/metric-receipts",
        _payload(),
        format="json",
    )
    assert response.status_code == 201
    assert MetricReceipt.objects.count() == 1
    assert MetricReceipt.objects.get().channel == "LINKEDIN"
