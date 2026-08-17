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
    assert [step.tool_name for step in first.steps] == [
        "analyze_post_performance",
        "propose_publish_calendar",
        "schedule_social_post",
    ]
    assert first.steps[0].outcome == "succeeded"
    assert first.steps[1].outcome == "succeeded"
    assert first.steps[2].outcome == "blocked_approval"
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
    assert calls[0]["scheduled_at"].isoformat() == "2026-08-20T09:00:00+00:00"


def test_analyze_post_performance_summary(monkeypatch):
    from apps.growth.agent import publishing_tools as pt
    from apps.growth import models as growth_models
    from apps import tracking
    from apps.publishing import models as publishing_models

    class FakeQs:
        def __init__(self, count):
            self._count = count

        def filter(self, **kwargs):
            return self

        def count(self):
            return self._count

        def aggregate(self, **kwargs):
            return {
                "impressions": 111,
                "plays": 22,
                "likes": 33,
                "comments": 44,
                "shares": 55,
            }

    monkeypatch.setattr(pt, "PublishedPost", SimpleNamespace(objects=FakeQs(3)))
    monkeypatch.setattr(tracking.models, "ClickEvent", SimpleNamespace(objects=FakeQs(4)))
    monkeypatch.setattr(growth_models, "InboundRfq", SimpleNamespace(objects=FakeQs(5)))
    monkeypatch.setattr(growth_models, "CRMHandoff", SimpleNamespace(objects=FakeQs(2)))
    monkeypatch.setattr(publishing_models, "PostMetric", SimpleNamespace(objects=FakeQs(0)))

    result = pt._summarize_performance(SimpleNamespace(id="org-1"))

    assert result == {
        "published_count": 3,
        "impressions": 111,
        "plays": 22,
        "likes": 33,
        "comments": 44,
        "shares": 55,
        "click_count": 4,
        "inquiry_count": 5,
        "crm_handoff_count": 2,
    }
