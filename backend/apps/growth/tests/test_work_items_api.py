import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.growth.models import ChannelPackage
from apps.identity.models import Membership, Organization, Role


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Work items", slug="work-items")


@pytest.fixture
def operator_client(db, organization):
    role = Role.objects.create_operator()
    user = get_user_model().objects.create_user(username="work-items-op", password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    return client


def test_work_items_endpoint_projects_social_review(organization, operator_client):
    ChannelPackage.objects.create(
        organization=organization,
        channel="LINKEDIN",
        payload={"title": "post"},
        status="AWAITING_REVIEW",
        is_demo=False,
    )
    response = operator_client.get("/api/v1/growth/work-items")
    assert response.status_code == 200
    assert any(item["kind"] == "SOCIAL_REVIEW" for item in response.data)


def test_read_only_user_cannot_view_work_items(organization):
    role = Role.objects.create_read_only()
    user = get_user_model().objects.create_user(username="work-items-ro", password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=user.username, password="password")
    response = client.get("/api/v1/growth/work-items")
    assert response.status_code == 403
