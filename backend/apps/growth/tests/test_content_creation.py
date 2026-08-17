import pytest
from django.contrib.auth import get_user_model
from types import SimpleNamespace

from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService
from apps.campaigns.models import ContentBrief
from apps.campaigns.services import create_campaign, create_content_brief
from apps.catalog.models import Product
from apps.growth.agent.content_creation_tools import run_content_creation_agent
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job
from apps.platforms.models import Platform


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Creation", slug="creation")


def test_content_creation_agent_marks_ready_and_triggers(organization, monkeypatch):
    user = get_user_model().objects.create_user(username="creator", password="pw")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    campaign = create_campaign(organization=organization, values={"name": "Content"}, product_ids=())
    brief = create_content_brief(
        organization=organization,
        campaign=campaign,
        creator=user,
        values={},
        product_ids=(),
        asset_ids=(),
        platform_ids=(),
        concept_links=(),
    )
    product = Product.objects.create(
        organization=organization,
        name_en="Precision gear",
        module_min="1.0000",
        module_max="2.0000",
        tooth_count_min=10,
        tooth_count_max=40,
        pressure_angle="20.000",
        manufacturing_capabilities=["hobbing"],
        inspection_capabilities=["CMM"],
        moq=1,
        status=Product.Status.ACTIVE,
    )
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    PromptVersionService.create(
        purpose="CONTENT_GENERATE",
        code="content-test",
        provider="fake",
        model="fake-v1",
        template="test",
        output_schema={"type": "object"},
        status=PromptVersion.Status.PUBLISHED,
    )
    monkeypatch.setattr(
        "apps.content.tasks.generate_master_content_job.delay",
        lambda *args, **kwargs: None,
    )

    result = run_content_creation_agent(
        organization=organization,
        brief_id=str(brief.id),
        actor_id=str(user.id),
        values={
            "target_country": "US",
            "customer_type": "Buyer",
            "content_objective": "Leads",
            "cta": "Quote",
            "landing_page_url": "https://example.com",
            "language": "en",
            "selling_points": ["Quality"],
            "advantages": ["Speed"],
            "keywords": ["gear"],
        },
        product_id=str(product.id),
        platform_id=str(platform.id),
    )

    assert result.status == "completed"
    brief.refresh_from_db()
    assert brief.status == ContentBrief.Status.READY
    assert Job.objects.filter(
        organization=organization,
        type=Job.Type.CONTENT_GENERATE,
    ).exists()


def test_platform_variants_tool_creates_per_platform(organization, monkeypatch):
    from apps.growth.agent import content_creation_tools as cct
    from apps.growth.agent.content_creation_tools import run_platform_variants_agent

    user = get_user_model().objects.create_user(username="variant-actor", password="pw")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    links = [
        SimpleNamespace(platform=SimpleNamespace(id="p1", code="LINKEDIN")),
        SimpleNamespace(platform=SimpleNamespace(id="p2", code="FACEBOOK")),
    ]
    fake_master = SimpleNamespace(
        id="m1",
        brief=SimpleNamespace(platform_links=SimpleNamespace(all=lambda: links)),
    )
    monkeypatch.setattr(cct, "_get_master", lambda org, master_id: fake_master)
    calls = []

    def fake_create(master, platform, actor):
        calls.append(platform.code)
        return SimpleNamespace(id=f"pc-{platform.code}", status="IN_REVIEW")

    monkeypatch.setattr(cct, "create_platform_content", fake_create)

    result = run_platform_variants_agent(
        organization=organization,
        master_id="m1",
        actor_id=str(user.id),
    )

    assert result.status == "completed"
    assert calls == ["LINKEDIN", "FACEBOOK"]
    variants = result.steps[-1].output["variants"]
    assert {variant["platform_code"] for variant in variants} == {"LINKEDIN", "FACEBOOK"}
