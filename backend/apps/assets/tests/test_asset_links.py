import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from apps.assets.models import AssetProductLink
from apps.assets.services import upload_asset
from apps.catalog.models import Product
from integrations.storage.memory_storage import MemoryObjectStorage

from .conftest import make_product
from .test_asset_upload import ChunkOnlyUpload


@pytest.fixture
def asset_and_products(organizations):
    own, other = organizations
    creator = get_user_model().objects.create_user(username="asset-link")
    asset = upload_asset(
        organization=own,
        creator=creator,
        upload=ChunkOnlyUpload([b"\x89PNG\r\n\x1a\nlink"]),
        asset_type="IMAGE",
        storage=MemoryObjectStorage(),
    )
    return asset, make_product(own, name="Own product"), make_product(other, name="Other product")


@pytest.mark.django_db
def test_direct_and_base_manager_paths_reject_cross_org_links(asset_and_products) -> None:
    asset, _, foreign_product = asset_and_products

    with pytest.raises(ValidationError):
        AssetProductLink._base_manager.create(
            organization=asset.organization,
            asset=asset,
            product=foreign_product,
        )

    with pytest.raises(ValidationError):
        AssetProductLink._base_manager.bulk_create(
            [
                AssetProductLink(
                    organization=asset.organization,
                    asset=asset,
                    product=foreign_product,
                )
            ]
        )
    assert AssetProductLink.objects.count() == 0


@pytest.mark.django_db
def test_link_duplicates_are_prevented(asset_and_products) -> None:
    asset, product, _ = asset_and_products
    AssetProductLink.objects.create(
        organization=asset.organization, asset=asset, product=product
    )

    with pytest.raises(ValidationError):
        AssetProductLink.objects.create(
            organization=asset.organization, asset=asset, product=product
        )

    assert AssetProductLink.objects.count() == 1


@pytest.mark.django_db
def test_link_identity_is_immutable_for_queryset_and_bulk_paths(asset_and_products) -> None:
    asset, product, foreign_product = asset_and_products
    link = AssetProductLink.objects.create(
        organization=asset.organization, asset=asset, product=product
    )

    with pytest.raises(ValidationError, match="immutable"):
        AssetProductLink.objects.filter(pk=link.pk).update(product=foreign_product)
    link.product = foreign_product
    with pytest.raises(ValidationError, match="immutable"):
        AssetProductLink.objects.bulk_update([link], ["product"])


@pytest.mark.django_db
def test_link_bulk_upsert_is_not_an_identity_update_escape_hatch() -> None:
    with pytest.raises(ValidationError, match="upsert"):
        AssetProductLink._base_manager.bulk_create(
            [],
            update_conflicts=True,
            update_fields=["updated_at"],
            unique_fields=["id"],
        )


@pytest.mark.django_db
def test_link_survives_product_archiving_and_protects_product(asset_and_products) -> None:
    asset, product, _ = asset_and_products
    link = AssetProductLink.objects.create(
        organization=asset.organization, asset=asset, product=product
    )

    product.status = Product.Status.ARCHIVED
    product.save()
    link.refresh_from_db()

    assert link.product_id == product.id
    with pytest.raises(ProtectedError):
        product.delete()
