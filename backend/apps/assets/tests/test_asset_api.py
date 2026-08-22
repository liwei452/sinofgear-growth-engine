import json

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.assets.models import AssetProductLink
from apps.assets.services import upload_asset
from apps.identity.models import Role
from integrations.storage.memory_storage import MemoryObjectStorage

from .conftest import create_member_client, make_product, png_bytes, upload_payload
from .test_asset_upload import ChunkOnlyUpload


@pytest.mark.django_db
def test_upload_detail_and_same_org_dedup_runtime_contract(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="api-upload"
    )
    payload = upload_payload(tags=["gear", "inspection"], metadata_json={"angle": 20})

    first = client.post("/api/v1/assets", payload, format="multipart")
    second = client.post(
        "/api/v1/assets",
        upload_payload(tags=["replacement"], metadata_json={"angle": 99}),
        format="multipart",
    )
    detail = client.get(f"/api/v1/assets/{first.json()['id']}")

    assert first.status_code == 201, first.json()
    assert second.status_code == 200, second.json()
    assert first.json()["id"] == second.json()["id"]
    assert detail.status_code == 200
    assert detail.json()["tags"] == ["gear", "inspection"]
    assert detail.json()["metadata_json"] == {"angle": 20}
    assert "storage_key" not in detail.json()
    assert "checksum" in detail.json()


@pytest.mark.django_db
def test_asset_archive_is_reversible_and_hidden_from_default_list(organizations, roles):
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username="asset-trash"
    )
    asset_id = client.post("/api/v1/assets", upload_payload(), format="multipart").json()["id"]

    archived = client.post(f"/api/v1/assets/{asset_id}/archive", {}, format="json")
    normal = client.get("/api/v1/assets")
    trash = client.get("/api/v1/assets?status=ARCHIVED")
    restored = client.post(f"/api/v1/assets/{asset_id}/restore", {}, format="json")

    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"
    assert normal.json()["results"] == []
    assert [row["id"] for row in trash.json()["results"]] == [asset_id]
    assert restored.json()["status"] == "ACTIVE"
    assert client.get("/api/v1/assets").json()["results"][0]["id"] == asset_id


@pytest.mark.django_db
def test_cross_org_asset_detail_and_download_are_non_leaking_404(organizations, roles) -> None:
    own, other = organizations
    _, own_client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="asset-owner"
    )
    _, other_client = create_member_client(
        organization=other, role=roles[Role.Code.ADMINISTRATOR], username="asset-foreigner"
    )
    asset_id = own_client.post(
        "/api/v1/assets", upload_payload(), format="multipart"
    ).json()["id"]

    detail = other_client.get(f"/api/v1/assets/{asset_id}")
    download = other_client.post(f"/api/v1/assets/{asset_id}/download-url")

    assert detail.status_code == 404
    assert download.status_code == 404
    assert detail.json() == {"detail": "Not found."}
    assert download.json() == {
        "detail": "Not found.",
        "code": "http_404",
        "message": "Not found.",
        "recovery_action": "Refresh the page and choose an available resource.",
    }


@pytest.mark.django_db
def test_signed_download_url_expires_in_exactly_300_seconds_without_secrets(
    organizations, roles
) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="asset-download"
    )
    operator_role = roles[Role.Code.OPERATOR]
    operator = get_user_model().objects.create_user(username="asset-uploader", password="pass")
    from apps.identity.models import Membership

    Membership.objects.create(user=operator, organization=own, role=operator_role)
    upload_client = type(client)()
    assert upload_client.login(username="asset-uploader", password="pass")
    asset_id = upload_client.post(
        "/api/v1/assets", upload_payload(), format="multipart"
    ).json()["id"]

    response = client.post(f"/api/v1/assets/{asset_id}/download-url")

    assert response.status_code == 200
    assert response.json()["expires_in"] == 300
    assert "expires=300" in response.json()["url"]
    serialized = json.dumps(response.json()).lower()
    assert "access_key" not in serialized
    assert "secret" not in serialized
    assert "password" not in serialized


@pytest.mark.django_db
def test_link_product_is_org_scoped_deduplicated_and_includes_archived_product(
    organizations, roles
) -> None:
    own, other = organizations
    own_product = make_product(own, name="Archived linked product", status="ARCHIVED")
    foreign_product = make_product(other, name="Foreign secret")
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username="asset-link-api"
    )
    asset_id = client.post(
        "/api/v1/assets", upload_payload(), format="multipart"
    ).json()["id"]

    linked = client.post(
        f"/api/v1/assets/{asset_id}/link-product",
        {"product_id": str(own_product.id)},
        format="json",
    )
    duplicate = client.post(
        f"/api/v1/assets/{asset_id}/link-product",
        {"product_id": str(own_product.id)},
        format="json",
    )
    foreign = client.post(
        f"/api/v1/assets/{asset_id}/link-product",
        {"product_id": str(foreign_product.id)},
        format="json",
    )

    assert linked.status_code == 201, linked.json()
    assert duplicate.status_code == 200
    assert foreign.status_code == 404
    assert [item["id"] for item in linked.json()["products"]] == [str(own_product.id)]
    assert linked.json()["products"][0]["status"] == "ARCHIVED"
    assert AssetProductLink.objects.count() == 1


@pytest.mark.django_db
def test_serializer_never_exposes_legacy_cross_org_product_link(organizations, roles) -> None:
    own, other = organizations
    own_product = make_product(own, name="Initially safe")
    foreign_product = make_product(other, name="Foreign product secret")
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.ADMINISTRATOR], username="legacy-asset-link"
    )
    asset_id = client.post(
        "/api/v1/assets", upload_payload(), format="multipart"
    ).json()["id"]
    client.post(
        f"/api/v1/assets/{asset_id}/link-product",
        {"product_id": str(own_product.id)},
        format="json",
    )
    link = AssetProductLink.objects.get(asset_id=asset_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE assets_assetproductlink SET product_id = %s WHERE id = %s",
            [foreign_product.id.hex, link.id.hex],
        )

    response = client.get(f"/api/v1/assets/{asset_id}")

    assert response.status_code == 200
    assert response.json()["products"] == []
    assert "Foreign product secret" not in response.content.decode()


@pytest.mark.django_db
def test_cursor_pagination_filters_and_repeated_parameter_rules(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.OPERATOR], username="asset-pages"
    )
    product = make_product(own, name="Filter product")
    asset_ids = []
    for index in range(4):
        created = client.post(
            "/api/v1/assets",
            upload_payload(
                content=png_bytes(bytes([index])),
                tags=["shared", f"tag-{index}"],
            ),
            format="multipart",
        )
        asset_ids.append(created.json()["id"])
        client.post(
            f"/api/v1/assets/{created.json()['id']}/link-product",
            {"product_id": str(product.id)},
            format="json",
        )

    first = client.get(
        f"/api/v1/assets?type=IMAGE&status=ACTIVE&product={product.id}"
        "&tag=shared&page_size=2"
    )
    second = client.get(first.json()["next"])
    repeated = client.get("/api/v1/assets?tag=one&tag=two")
    invalid = client.get("/api/v1/assets?type=UNKNOWN&product=not-a-uuid")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "type=IMAGE" in first.json()["next"]
    assert "tag=shared" in first.json()["next"]
    assert [item["id"] for item in first.json()["results"] + second.json()["results"]] == list(
        reversed(asset_ids)
    )
    assert repeated.status_code == 400
    assert "tag" in repeated.json()["errors"]
    assert invalid.status_code == 400
    assert {"type", "product"} <= set(invalid.json()["errors"])


@pytest.mark.django_db
def test_asset_list_product_links_have_bounded_query_count(
    organizations, roles, django_assert_num_queries
) -> None:
    own, _ = organizations
    creator = get_user_model().objects.create_user(username="query-asset-creator")
    product = make_product(own, name="Query product")
    for index in range(4):
        asset = upload_asset(
            organization=own,
            creator=creator,
            upload=ChunkOnlyUpload([png_bytes(b"query" + bytes([index]))]),
            asset_type="IMAGE",
            storage=MemoryObjectStorage(),
        )
        AssetProductLink.objects.create(organization=own, asset=asset, product=product)
    _, client = create_member_client(
        organization=own, role=roles[Role.Code.READ_ONLY], username="asset-query-reader"
    )

    with django_assert_num_queries(7):
        response = client.get("/api/v1/assets")

    assert response.status_code == 200
    assert all(len(item["products"]) == 1 for item in response.json()["results"])
