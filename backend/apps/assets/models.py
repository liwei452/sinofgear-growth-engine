import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models.expressions import BaseExpression

from apps.catalog.models import Product
from apps.common.models import OrganizationScopedModel


ORIGINAL_IDENTITY_FIELDS = frozenset(
    {
        "organization",
        "organization_id",
        "asset_type",
        "storage_key",
        "original_filename",
        "mime_type",
        "size_bytes",
        "checksum",
        "created_by",
        "created_by_id",
    }
)
LINK_IDENTITY_FIELDS = frozenset(
    {"organization", "organization_id", "asset", "asset_id", "product", "product_id"}
)


def validate_tags(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError("Tags must be a JSON list of unique non-blank strings.")
    if len(value) > 50:
        raise ValidationError("At most 50 tags are allowed.")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValidationError("Every tag must be a non-blank string.")
    if any(len(item) > 64 for item in value):
        raise ValidationError("Tags may contain at most 64 characters.")
    if len(value) != len(set(value)):
        raise ValidationError("Tags must be unique.")


def _validate_json_keys(value: object) -> None:
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValidationError("Metadata object keys must be strings.")
        for child in value.values():
            _validate_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json_keys(child)


def validate_metadata_json(value: object) -> None:
    if not isinstance(value, dict):
        raise ValidationError("Metadata must be a JSON object.")
    _validate_json_keys(value)
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValidationError("Metadata must contain only valid JSON values.") from error


class MaterialAssetQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        if ORIGINAL_IDENTITY_FIELDS & set(kwargs):
            raise ValidationError("Original asset binary identity is immutable.")
        rows = list(self.select_for_update().order_by("pk"))
        for row in rows:
            for field, value in kwargs.items():
                if isinstance(value, BaseExpression):
                    raise ValidationError(
                        f"Expression updates are not supported for asset field '{field}'."
                    )
                setattr(row, field, value)
            row.save(update_fields=[*kwargs, "updated_at"])
        return len(rows)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Asset bulk upserts are not supported.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.full_clean()
        return super().bulk_create(rows, **kwargs)

    @transaction.atomic
    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if ORIGINAL_IDENTITY_FIELDS & field_names:
            raise ValidationError("Original asset binary identity is immutable.")
        rows = sorted(objs, key=lambda row: str(row.pk))
        for row in rows:
            row.save(update_fields=[*field_names, "updated_at"])
        return len(rows)


class MaterialAssetManager(models.Manager.from_queryset(MaterialAssetQuerySet)):
    pass


class MaterialAsset(OrganizationScopedModel):
    class AssetType(models.TextChoices):
        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Document"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    asset_type = models.CharField(max_length=16, choices=AssetType.choices)
    storage_key = models.CharField(max_length=512, unique=True)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=127)
    size_bytes = models.PositiveBigIntegerField()
    checksum = models.CharField(
        max_length=64,
        validators=[RegexValidator(r"^[0-9a-f]{64}$", "Checksum must be lowercase SHA-256.")],
    )
    language = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    tags = models.JSONField(default=list, blank=True, validators=[validate_tags])
    metadata_json = models.JSONField(default=dict, blank=True, validators=[validate_metadata_json])
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_material_assets",
    )

    objects = MaterialAssetManager()

    class Meta:
        ordering = ["-created_at", "-id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "checksum"],
                name="assets_unique_organization_checksum",
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name="assets_material_size_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "asset_type", "status", "created_at"],
                name="assets_org_type_status_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        validate_tags(self.tags)
        validate_metadata_json(self.metadata_json)
        if self.organization_id and self.id:
            expected = f"organizations/{self.organization_id}/assets/{self.id}/original"
            if self.storage_key != expected:
                raise ValidationError(
                    {"storage_key": "Storage key must use the organization-isolated original path."}
                )

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            original = type(self).objects.select_for_update().get(pk=self.pk)
            if any(
                getattr(self, field.removesuffix("_id") + "_id", None)
                != getattr(original, field.removesuffix("_id") + "_id", None)
                if field in {"organization", "organization_id", "created_by", "created_by_id"}
                else getattr(self, field) != getattr(original, field)
                for field in (
                    "organization_id",
                    "asset_type",
                    "storage_key",
                    "original_filename",
                    "mime_type",
                    "size_bytes",
                    "checksum",
                    "created_by_id",
                )
            ):
                raise ValidationError("Original asset binary identity is immutable.")
        self.full_clean()
        super().save(*args, **kwargs)


def _lock_and_refresh_link_references(links) -> None:
    asset_ids = sorted({link.asset_id for link in links}, key=str)
    assets = {
        asset.id: asset
        for asset in MaterialAsset.objects.filter(pk__in=asset_ids)
        .order_by("id")
        .select_for_update(of=("self",))
    }
    product_ids = sorted({link.product_id for link in links}, key=str)
    products = {
        product.id: product
        for product in Product.objects.filter(pk__in=product_ids)
        .order_by("id")
        .select_for_update(of=("self",))
    }
    for link in links:
        if link.asset_id not in assets:
            raise ValidationError({"asset": "Asset does not exist."})
        if link.product_id not in products:
            raise ValidationError({"product": "Product does not exist."})
        link.asset = assets[link.asset_id]
        link.product = products[link.product_id]


class AssetProductLinkQuerySet(models.QuerySet):
    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Asset product link bulk upserts are not supported.")
        links = list(objs)
        _lock_and_refresh_link_references(links)
        for link in links:
            link.full_clean()
        return super().bulk_create(links, **kwargs)

    def update(self, **kwargs):
        if LINK_IDENTITY_FIELDS & set(kwargs):
            raise ValidationError("Asset product link identity is immutable.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if LINK_IDENTITY_FIELDS & field_names:
            raise ValidationError("Asset product link identity is immutable.")
        return super().bulk_update(objs, fields, **kwargs)


class AssetProductLinkManager(models.Manager.from_queryset(AssetProductLinkQuerySet)):
    pass


class AssetProductLink(OrganizationScopedModel):
    asset = models.ForeignKey(
        MaterialAsset,
        on_delete=models.PROTECT,
        related_name="product_links",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="asset_links",
    )

    objects = AssetProductLinkManager()

    class Meta:
        ordering = ["product__name_en", "id"]
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "product"],
                name="assets_unique_asset_product",
            )
        ]
        indexes = [
            models.Index(
                fields=["organization", "asset"],
                name="assets_org_asset_link_idx",
            )
        ]

    def clean(self) -> None:
        super().clean()
        if not self.organization_id or not self.asset_id or not self.product_id:
            return
        if self.asset.organization_id != self.organization_id:
            raise ValidationError({"asset": "Asset must belong to the link organization."})
        if self.product.organization_id != self.organization_id:
            raise ValidationError({"product": "Product must belong to the link organization."})

    @transaction.atomic
    def save(self, *args, **kwargs) -> None:
        if self._state.adding:
            _lock_and_refresh_link_references([self])
        else:
            original = type(self).objects.select_for_update().get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field)
                for field in ("organization_id", "asset_id", "product_id")
            ):
                raise ValidationError("Asset product link identity is immutable.")
        self.full_clean()
        super().save(*args, **kwargs)
