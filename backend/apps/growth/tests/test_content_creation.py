import uuid

import pytest
from django.contrib.auth import get_user_model
from types import SimpleNamespace

from apps.ai.models import PromptVersion
from apps.ai.services import PromptVersionService
from apps.assets.models import MaterialAsset
from apps.campaigns.models import ContentBrief
from apps.campaigns.services import create_campaign, create_content_brief
from apps.catalog.models import Product
from apps.growth.agent.content_creation_tools import (
    _auto_match_assets,
    build_content_creation_tools,
    run_content_creation_agent,
)
from apps.growth.agent.tools import ToolRegistry
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

    def run(approvals):
        return run_content_creation_agent(
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
            approvals=approvals,
        )

    first = run(None)
    assert first.status == "waiting_approval"
    token1 = first.pending_approval.approval_token

    second = run({token1})
    assert second.status == "waiting_approval"
    token2 = second.pending_approval.approval_token

    third = run({token1, token2})
    assert third.status == "waiting_approval"
    token3 = third.pending_approval.approval_token

    result = run({token1, token2, token3})
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

    first = run_platform_variants_agent(
        organization=organization,
        master_id="m1",
        actor_id=str(user.id),
    )
    assert first.status == "waiting_approval"
    token = first.pending_approval.approval_token

    result = run_platform_variants_agent(
        organization=organization,
        master_id="m1",
        actor_id=str(user.id),
        approvals={token},
    )

    assert result.status == "completed"
    assert calls == ["LINKEDIN", "FACEBOOK"]
    variants = result.steps[-1].output["variants"]
    assert {variant["platform_code"] for variant in variants} == {"LINKEDIN", "FACEBOOK"}


def test_content_creation_enrich_tool_binds_assets(organization):
    user = get_user_model().objects.create_user(username="asset-binder", password="pw")
    Membership.objects.create(
        user=user,
        organization=organization,
        role=Role.objects.create_operator(),
    )
    campaign = create_campaign(organization=organization, values={"name": "Asset"}, product_ids=())
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
    asset_id = uuid.uuid4()
    asset = MaterialAsset.objects.create(
        id=asset_id,
        organization=organization,
        asset_type=MaterialAsset.AssetType.DOCUMENT,
        storage_key=f"organizations/{organization.id}/assets/{asset_id}/original",
        original_filename="proof.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum="a" * 64,
        created_by=user,
    )

    tools = ToolRegistry(build_content_creation_tools(organization, str(user.id)))
    result = tools.get("enrich_content_brief").func({
        "brief_id": str(brief.id),
        "values": {
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
        "product_ids": [],
        "platform_ids": [],
        "asset_ids": [str(asset.id)],
    })

    assert result.ok is True
    brief.refresh_from_db()
    assert list(brief.asset_links.values_list("asset_id", flat=True)) == [asset.id]


def test_missing_media_requirements_detects_platforms_without_matching_assets():
    from apps.growth.agent import content_creation_tools as cct

    brief = SimpleNamespace(
        platform_links=SimpleNamespace(select_related=lambda name: [
            SimpleNamespace(platform=SimpleNamespace(code="INSTAGRAM")),
            SimpleNamespace(platform=SimpleNamespace(code="TIKTOK")),
            SimpleNamespace(platform=SimpleNamespace(code="LINKEDIN")),
        ]),
        asset_links=SimpleNamespace(select_related=lambda name: [
            SimpleNamespace(asset=SimpleNamespace(mime_type="application/pdf")),
        ]),
    )

    missing = cct._missing_media_requirements(brief)

    assert missing == ["INSTAGRAM", "TIKTOK"]


def test_auto_match_assets_prefers_matching_media(organization):
    platform = Platform.objects.create(code="INSTAGRAM", name="Instagram")
    actor = get_user_model().objects.create_user(username="asset-matcher", password="pw")
    image_id = uuid.uuid4()
    image = MaterialAsset.objects.create(
        id=image_id,
        organization=organization,
        asset_type=MaterialAsset.AssetType.IMAGE,
        storage_key=f"organizations/{organization.id}/assets/{image_id}/original",
        original_filename="hero.png",
        mime_type="image/png",
        size_bytes=10,
        checksum="b" * 64,
        created_by=actor,
    )
    document_id = uuid.uuid4()
    MaterialAsset.objects.create(
        id=document_id,
        organization=organization,
        asset_type=MaterialAsset.AssetType.DOCUMENT,
        storage_key=f"organizations/{organization.id}/assets/{document_id}/original",
        original_filename="notes.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum="c" * 64,
        created_by=actor,
    )

    matched = _auto_match_assets(organization, platform.id)

    assert matched == [str(image.id)]
