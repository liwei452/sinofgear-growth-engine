import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.identity.models import Membership, Organization, Role


@pytest.fixture
def api_organizations(db):
    return (
        Organization.objects.create(name="Jobs API Own", slug="jobs-api-own"),
        Organization.objects.create(name="Jobs API Other", slug="jobs-api-other"),
    )


@pytest.fixture
def api_roles(db):
    return {
        role.code: role
        for role in (
            Role.objects.create_administrator(),
            Role.objects.create_operator(),
            Role.objects.create_reviewer(),
            Role.objects.create_read_only(),
        )
    }


def member_client(*, organization, role, username):
    user = get_user_model().objects.create_user(username=username, password="password")
    Membership.objects.create(user=user, organization=organization, role=role)
    client = APIClient()
    assert client.login(username=username, password="password")
    return user, client
