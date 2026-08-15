import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.db import connection

from apps.campaigns.models import Campaign, ContentBrief
from apps.identity.models import Role

from .conftest import create_member_client, make_platform, make_product, valid_brief_values
from .conftest import make_asset, make_concept
from apps.campaigns.models import (
    CampaignProduct,
    ContentBriefProduct,
)


@pytest.mark.django_db
def test_operator_campaign_crud_is_org_scoped_and_cursor_paginated(
    campaign_organizations, campaign_roles
):
    own, other = campaign_organizations
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.OPERATOR], username="campaign-op"
    )
    foreign = Campaign.objects.create(organization=other, name="Foreign secret")

    created = client.post(
        "/api/v1/campaigns", {"name": "Gear launch", "description": "EU"}, format="json"
    )
    listing = client.get("/api/v1/campaigns?page_size=1&status=DRAFT")
    updated = client.patch(
        f"/api/v1/campaigns/{created.json()['id']}", {"description": "Germany"}, format="json"
    )
    hidden = client.get(f"/api/v1/campaigns/{foreign.id}")

    assert created.status_code == 201, created.json()
    assert listing.status_code == 200
    assert listing.json()["results"][0]["name"] == "Gear launch"
    assert updated.status_code == 200
    assert updated.json()["description"] == "Germany"
    assert updated.json()["version"] == 2
    assert hidden.status_code == 404


@pytest.mark.django_db
def test_operator_creates_and_edits_draft_but_only_reviewer_or_admin_marks_ready(
    campaign_organizations, campaign_roles
):
    own, _ = campaign_organizations
    product = make_product(own)
    platform = make_platform()
    operator, operator_client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.OPERATOR], username="brief-op"
    )
    _, reviewer_client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.REVIEWER], username="brief-reviewer"
    )
    campaign_id = operator_client.post(
        "/api/v1/campaigns", {"name": "Launch"}, format="json"
    ).json()["id"]
    payload = {
        "campaign_id": campaign_id,
        **valid_brief_values(),
        "product_ids": [str(product.id)],
        "asset_ids": [],
        "platform_ids": [str(platform.id)],
        "concept_links": [],
    }

    created = operator_client.post("/api/v1/content-briefs", payload, format="json")
    brief_id = created.json()["id"]
    edited = operator_client.patch(
        f"/api/v1/content-briefs/{brief_id}", {"cta": "Contact sales"}, format="json"
    )
    forbidden = operator_client.post(f"/api/v1/content-briefs/{brief_id}/ready")
    ready = reviewer_client.post(f"/api/v1/content-briefs/{brief_id}/ready")
    immutable = operator_client.patch(
        f"/api/v1/content-briefs/{brief_id}", {"cta": "Bypass"}, format="json"
    )

    assert created.status_code == 201, created.json()
    assert created.json()["created_by"] == operator.id
    assert edited.status_code == 200
    assert forbidden.status_code == 403
    assert ready.status_code == 200, ready.json()
    assert ready.json()["status"] == "READY"
    assert immutable.status_code == 400
    assert "errors" in immutable.json()


@pytest.mark.django_db
def test_read_only_can_view_but_not_write_and_malformed_values_are_json_errors(
    campaign_organizations, campaign_roles
):
    own, _ = campaign_organizations
    Campaign.objects.create(organization=own, name="Visible")
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.READ_ONLY], username="campaign-reader"
    )

    listing = client.get("/api/v1/campaigns")
    forbidden = client.post("/api/v1/campaigns", {"name": "No"}, format="json")
    malformed_filter = client.get("/api/v1/content-briefs?campaign=not-a-uuid")
    malformed_path = client.get("/api/v1/content-briefs/not-a-uuid")

    assert listing.status_code == 200
    assert forbidden.status_code == 403
    assert malformed_filter.status_code == 400
    assert malformed_filter.json().keys() == {"errors"}
    assert malformed_path.status_code == 404


@pytest.mark.django_db
def test_brief_list_filters_status_and_campaign_without_cross_org_leak(
    campaign_organizations, campaign_roles, campaign_user
):
    own, other = campaign_organizations
    own_campaign = Campaign.objects.create(organization=own, name="Own")
    other_campaign = Campaign.objects.create(organization=other, name="Other")
    ContentBrief.objects.create(
        organization=own, campaign=own_campaign, created_by=campaign_user
    )
    foreign_user, _ = create_member_client(
        organization=other,
        role=campaign_roles[Role.Code.OPERATOR],
        username="foreign-brief-owner",
    )
    ContentBrief.objects.create(
        organization=other, campaign=other_campaign, created_by=foreign_user
    )
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.READ_ONLY], username="brief-reader"
    )

    response = client.get(
        f"/api/v1/content-briefs?status=DRAFT&campaign={own_campaign.id}&page_size=1"
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1
    assert response.json()["results"][0]["campaign_id"] == str(own_campaign.id)


@pytest.mark.django_db
def test_content_brief_archive_restores_exact_status_and_default_list_hides_it(
    campaign_organizations, campaign_roles, campaign_user
):
    own, _ = campaign_organizations
    campaign = Campaign.objects.create(organization=own, name="Trash test")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=campaign_user
    )
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.ADMINISTRATOR], username="brief-trash"
    )

    assert client.post(f"/api/v1/content-briefs/{brief.id}/archive", {}, format="json").json()["status"] == "ARCHIVED"
    assert client.get("/api/v1/content-briefs").json()["results"] == []
    assert client.get("/api/v1/content-briefs?status=ARCHIVED").json()["results"][0]["id"] == str(brief.id)
    restored = client.post(f"/api/v1/content-briefs/{brief.id}/restore", {}, format="json")
    assert restored.json()["status"] == "DRAFT"


@pytest.mark.django_db
def test_campaign_permission_migration_seeds_builtin_roles_without_touching_custom_role(
    campaign_roles,
):
    custom = Role.objects.create(
        code="CUSTOM_CAMPAIGN", name="Custom", permissions=["custom.permission"]
    )
    migration = importlib.import_module(
        "apps.identity.migrations.0005_refresh_campaign_permissions"
    )

    migration.refresh_builtin_role_permissions(django_apps, None)

    assert {"campaigns.read", "campaigns.manage", "campaigns.review"} <= set(
        Role.objects.get(code=Role.Code.ADMINISTRATOR).permissions
    )
    assert {"campaigns.read", "campaigns.manage"} <= set(
        Role.objects.get(code=Role.Code.OPERATOR).permissions
    )
    assert {"campaigns.read", "campaigns.review"} <= set(
        Role.objects.get(code=Role.Code.REVIEWER).permissions
    )
    assert "campaigns.read" in Role.objects.get(code=Role.Code.READ_ONLY).permissions
    custom.refresh_from_db()
    assert custom.permissions == ["custom.permission"]


@pytest.mark.django_db
def test_campaign_permission_migration_merges_without_erasing_builtin_custom_permissions(
    campaign_roles,
):
    operator = campaign_roles[Role.Code.OPERATOR]
    operator.permissions = ["legacy.custom", "products.read"]
    operator.save(update_fields=["permissions"])
    migration = importlib.import_module(
        "apps.identity.migrations.0005_refresh_campaign_permissions"
    )

    migration.refresh_builtin_role_permissions(django_apps, None)

    operator.refresh_from_db()
    assert operator.permissions == [
        "legacy.custom", "products.read", "campaigns.read", "campaigns.manage"
    ]


@pytest.mark.django_db
def test_campaign_openapi_documents_lists_crud_filters_and_lifecycle_action(client):
    response = client.get("/api/v1/schema")
    schema = response.json()

    assert response.status_code == 200
    assert {"get", "post"} <= set(schema["paths"]["/api/v1/campaigns"])
    assert {"get", "patch", "delete"} <= set(
        schema["paths"]["/api/v1/campaigns/{campaign_id}"]
    )
    assert {"get", "post"} <= set(schema["paths"]["/api/v1/content-briefs"])
    assert {"get", "patch", "delete"} <= set(
        schema["paths"]["/api/v1/content-briefs/{brief_id}"]
    )
    assert "post" in schema["paths"]["/api/v1/content-briefs/{brief_id}/ready"]
    parameters = schema["paths"]["/api/v1/content-briefs"]["get"]["parameters"]
    assert {item["name"] for item in parameters} >= {
        "status", "campaign", "cursor", "page_size"
    }


@pytest.mark.django_db
def test_brief_list_serialization_has_bounded_query_count(
    campaign_organizations, campaign_roles, django_assert_max_num_queries
):
    own, _ = campaign_organizations
    user, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.OPERATOR], username="bounded"
    )
    campaign = Campaign.objects.create(organization=own, name="Bounded")
    for _ in range(3):
        ContentBrief.objects.create(
            organization=own, campaign=campaign, created_by=user
        )

    with django_assert_max_num_queries(12):
        response = client.get("/api/v1/content-briefs")

    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


@pytest.mark.django_db
def test_brief_patch_atomically_replaces_relationships_and_versions_once(
    campaign_organizations, campaign_roles
):
    own, _ = campaign_organizations
    first = make_product(own, name="First")
    second = make_product(own, name="Second")
    platform = make_platform()
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.OPERATOR], username="replace-api"
    )
    campaign_id = client.post("/api/v1/campaigns", {"name": "Replace"}, format="json").json()["id"]
    payload = {
        "campaign_id": campaign_id,
        **valid_brief_values(),
        "product_ids": [str(first.id)],
        "asset_ids": [],
        "platform_ids": [str(platform.id)],
        "concept_links": [],
    }
    brief_id = client.post("/api/v1/content-briefs", payload, format="json").json()["id"]

    response = client.patch(
        f"/api/v1/content-briefs/{brief_id}",
        {"product_ids": [str(second.id)]},
        format="json",
    )

    assert response.status_code == 200, response.json()
    assert response.json()["product_ids"] == [str(second.id)]
    assert response.json()["version"] == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/v1/campaigns", {"name": "Unknown", "mystery": 1}),
        ("patch", "/api/v1/campaigns/{campaign_id}", {"mystery": 1}),
        ("post", "/api/v1/content-briefs", {"mystery": 1}),
        ("patch", "/api/v1/content-briefs/{brief_id}", {"mystery": 1}),
        ("post", "/api/v1/content-briefs/{brief_id}/ready", {"mystery": 1}),
        ("post", "/api/v1/content-briefs/{brief_id}/revisions", {"mystery": 1}),
    ],
)
def test_unknown_request_fields_return_standard_json_400(
    campaign_organizations, campaign_roles, method, path, payload
):
    own, _ = campaign_organizations
    _, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.ADMINISTRATOR], username=f"unknown-{method}-{len(path)}"
    )
    campaign = Campaign.objects.create(organization=own, name="Existing")
    from django.contrib.auth import get_user_model
    creator = get_user_model().objects.get(username=f"unknown-{method}-{len(path)}")
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=creator
    )
    target = path.format(campaign_id=campaign.id, brief_id=brief.id)

    response = getattr(client, method)(target, payload, format="json")

    assert response.status_code == 400
    assert response.json() == {
        "errors": {"mystery": ["Unknown field."]},
        "code": "http_400",
        "message": "The request contains invalid fields.",
        "recovery_action": "Correct the request and try again.",
    }


@pytest.mark.django_db
def test_corrupt_foreign_relationship_identifiers_are_omitted_from_api(
    campaign_organizations, campaign_roles
):
    own, other = campaign_organizations
    own_product = make_product(own, name="Own")
    foreign_product = make_product(other, name="Foreign")
    user, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.OPERATOR], username="legacy-safe"
    )
    foreign_asset = make_asset(other, user, checksum_char="b")
    foreign_concept = make_concept(
        other, concept_type="INDUSTRY", code="FOREIGN_LEGACY"
    )
    campaign = Campaign.objects.create(organization=own, name="Legacy")
    campaign_link = CampaignProduct.objects.create(
        organization=own, campaign=campaign, product=own_product
    )
    brief = ContentBrief.objects.create(
        organization=own, campaign=campaign, created_by=user
    )
    product_link = ContentBriefProduct.objects.create(
        organization=own, brief=brief, product=own_product
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE campaigns_campaignproduct SET product_id=%s WHERE id=%s",
            [foreign_product.id.hex, campaign_link.id.hex],
        )
        cursor.execute(
            "UPDATE campaigns_contentbriefproduct SET product_id=%s WHERE id=%s",
            [foreign_product.id.hex, product_link.id.hex],
        )
        cursor.execute(
            "INSERT INTO campaigns_contentbriefasset "
            "(id, created_at, updated_at, organization_id, brief_id, asset_id) "
            "VALUES (%s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s, %s)",
            [uuid.uuid4().hex, own.id.hex, brief.id.hex, foreign_asset.id.hex],
        )
        cursor.execute(
            "INSERT INTO campaigns_contentbriefconceptlink "
            "(id, created_at, updated_at, organization_id, brief_id, concept_id, role) "
            "VALUES (%s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, %s, %s, %s, %s)",
            [uuid.uuid4().hex, own.id.hex, brief.id.hex, foreign_concept.id.hex, "TARGET_INDUSTRY"],
        )

    campaign_response = client.get(f"/api/v1/campaigns/{campaign.id}")
    brief_response = client.get(f"/api/v1/content-briefs/{brief.id}")

    assert campaign_response.status_code == 200
    assert campaign_response.json()["product_ids"] == []
    assert brief_response.status_code == 200
    assert brief_response.json()["product_ids"] == []
    assert brief_response.json()["asset_ids"] == []
    assert brief_response.json()["concept_links"] == []


@pytest.mark.django_db
def test_corrupt_foreign_campaign_or_predecessor_makes_brief_non_visible(
    campaign_organizations, campaign_roles
):
    own, other = campaign_organizations
    user, client = create_member_client(
        organization=own, role=campaign_roles[Role.Code.READ_ONLY], username="legacy-root"
    )
    own_campaign = Campaign.objects.create(organization=own, name="Own")
    foreign_campaign = Campaign.objects.create(organization=other, name="Foreign")
    first = ContentBrief.objects.create(
        organization=own, campaign=own_campaign, created_by=user
    )
    second = ContentBrief.objects.create(
        organization=own, campaign=own_campaign, created_by=user
    )
    foreign_source = ContentBrief.objects.create(
        organization=other, campaign=foreign_campaign, created_by=user
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE campaigns_contentbrief SET campaign_id=%s WHERE id=%s",
            [foreign_campaign.id.hex, first.id.hex],
        )
        cursor.execute(
            "UPDATE campaigns_contentbrief SET previous_version_id=%s WHERE id=%s",
            [foreign_source.id.hex, second.id.hex],
        )

    assert client.get(f"/api/v1/content-briefs/{first.id}").status_code == 404
    assert client.get(f"/api/v1/content-briefs/{second.id}").status_code == 404
