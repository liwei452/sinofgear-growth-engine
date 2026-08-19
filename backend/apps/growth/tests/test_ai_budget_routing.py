import pytest

from apps.ai.provider_config import ProductAIRuntime
from apps.ai.services import BudgetedAIProvider
from apps.growth import promotion_plan
from apps.identity.models import Organization
from apps.ai.models import OrganizationAIProviderConfig


class RecordingProvider:
    """Fake real provider: returns a valid plan payload and records calls."""

    last_usage = None

    def __init__(self):
        self.calls = 0

    def generate(self, *, prompt, schema):
        self.calls += 1
        return {"target_markets": [], "industries": [], "channels": []}


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Budget Routing Org", slug="budget-routing-org")


def _runtime(organization, provider):
    return ProductAIRuntime(
        mode="CONFIGURED_AI",
        provider_label="DeepSeek 官方 API",
        provider_code="deepseek",
        model="deepseek-chat",
        configured=True,
        real_requests_enabled=True,
        provider=provider,
    )


@pytest.mark.django_db
def test_promotion_plan_generation_reserves_and_settles_budget(organization, monkeypatch):
    config = OrganizationAIProviderConfig.objects.create(
        organization=organization,
        model="deepseek-chat",
        daily_budget_micros=2_000_000,
    )
    provider = RecordingProvider()
    monkeypatch.setattr(
        promotion_plan, "resolve_product_ai", lambda org: _runtime(org, provider)
    )

    result = promotion_plan.generate_promotion_plan(organization)

    assert result == {"target_markets": [], "industries": [], "channels": []}
    assert provider.calls == 1
    config.refresh_from_db()
    assert config.daily_spent_micros > 0
    assert config.daily_reserved_micros == 0


@pytest.mark.django_db
def test_promotion_plan_falls_back_when_budget_exceeded(organization, monkeypatch):
    OrganizationAIProviderConfig.objects.create(
        organization=organization,
        model="deepseek-chat",
        daily_budget_micros=1,
    )
    provider = RecordingProvider()
    monkeypatch.setattr(
        promotion_plan, "resolve_product_ai", lambda org: _runtime(org, provider)
    )

    result = promotion_plan.generate_promotion_plan(organization)

    # Budget exhaustion must fall back to the deterministic plan instead of
    # silently spending past the organization limit.
    assert provider.calls == 0
    assert result["target_markets"] == []
    assert "channels" in result


@pytest.mark.django_db
def test_budgeted_provider_settles_after_provider_error(organization):
    class ExplodingProvider:
        last_usage = None

        def generate(self, *, prompt, schema):
            raise RuntimeError("provider down")

    OrganizationAIProviderConfig.objects.create(
        organization=organization,
        model="deepseek-chat",
        daily_budget_micros=2_000_000,
    )
    budgeted = BudgetedAIProvider(
        organization=organization,
        model="deepseek-chat",
        provider=ExplodingProvider(),
    )

    with pytest.raises(RuntimeError):
        budgeted.generate(prompt="x" * 400, schema={"type": "object"})

    config = OrganizationAIProviderConfig.objects.get(organization=organization)
    assert config.daily_reserved_micros == 0
