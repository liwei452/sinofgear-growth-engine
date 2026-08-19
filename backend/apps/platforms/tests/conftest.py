from __future__ import annotations

import uuid

import pytest

from apps.identity.models import Organization, Role

from .buffer_test_utils import FakeConnector, FakeTokenStore, authenticated_member


@pytest.fixture
def buffer_api(monkeypatch):
    from apps.platforms import views as platform_views

    token_store = FakeTokenStore()
    connector = FakeConnector()
    monkeypatch.setattr(platform_views, "buffer_token_store", token_store, raising=False)
    monkeypatch.setattr(
        platform_views, "buffer_connector_factory", lambda: connector, raising=False,
    )
    return token_store, connector


@pytest.fixture
def organization():
    return Organization.objects.create(name="Acme", slug=f"acme-{uuid.uuid4().hex[:10]}")


@pytest.fixture
def admin_client(organization):
    return authenticated_member(
        organization=organization,
        role=Role.objects.create_administrator(),
        prefix="admin",
    )


@pytest.fixture
def reader_client(organization):
    return authenticated_member(
        organization=organization,
        role=Role.objects.create_reviewer(),
        prefix="reader",
    )
