import pytest
from types import SimpleNamespace

from apps.growth.agent import publishing_tools as pt
from apps.growth.agent.publishing_tools import run_social_ops_agent
from apps.identity.models import Organization


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Publishing", slug="publishing")


def test_social_ops_agent_requires_approval_before_publishing(organization, monkeypatch):
    content = SimpleNamespace(id="c1", organization_id=organization.id)
    account = SimpleNamespace(id="a1", organization_id=organization.id)
    monkeypatch.setattr(pt, "_get_content", lambda org, content_id: content)
    monkeypatch.setattr(pt, "_get_account", lambda org, account_id: account)
    calls = []
    monkeypatch.setattr(
        pt,
        "create_publish_task",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(id="t1", status="SCHEDULED"),
    )

    first = run_social_ops_agent(
        organization=organization,
        content_id="c1",
        account_id="a1",
        scheduled_at="2026-08-20T09:00:00Z",
    )
    assert first.status == "waiting_approval"
    assert calls == []
    token = first.pending_approval.approval_token

    resumed = run_social_ops_agent(
        organization=organization,
        content_id="c1",
        account_id="a1",
        scheduled_at="2026-08-20T09:00:00Z",
        approvals={token},
    )
    assert resumed.status == "completed"
    assert len(calls) == 1
    assert calls[0]["scheduled_at"] == "2026-08-20T09:00:00Z"
