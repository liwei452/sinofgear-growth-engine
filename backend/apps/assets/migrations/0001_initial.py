import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.assets.models
import uuid


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("catalog", "0003_remove_product_concepts"),
        ("identity", "0004_refresh_asset_permissions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MaterialAsset",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "asset_type",
                    models.CharField(
                        choices=[
                            ("IMAGE", "Image"),
                            ("VIDEO", "Video"),
                            ("DOCUMENT", "Document"),
                        ],
                        max_length=16,
                    ),
                ),
                ("storage_key", models.CharField(max_length=512, unique=True)),
                ("original_filename", models.CharField(max_length=255)),
                ("mime_type", models.CharField(max_length=127)),
                ("size_bytes", models.PositiveBigIntegerField()),
                (
                    "checksum",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[0-9a-f]{64}$",
                                "Checksum must be lowercase SHA-256.",
                            )
                        ],
                    ),
                ),
                ("language", models.CharField(blank=True, max_length=16)),
                (
                    "status",
                    models.CharField(
                        choices=[("ACTIVE", "Active"), ("ARCHIVED", "Archived")],
                        default="ACTIVE",
                        max_length=16,
                    ),
                ),
                (
                    "tags",
                    models.JSONField(
                        blank=True,
                        default=list,
                        validators=[apps.assets.models.validate_tags],
                    ),
                ),
                (
                    "metadata_json",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        validators=[apps.assets.models.validate_metadata_json],
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_material_assets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="identity.organization",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["organization", "asset_type", "status", "created_at"],
                        name="assets_org_type_status_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization", "checksum"),
                        name="assets_unique_organization_checksum",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("size_bytes__gt", 0)),
                        name="assets_material_size_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AssetProductLink",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="product_links",
                        to="assets.materialasset",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="identity.organization",
                    ),
                ),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="asset_links",
                        to="catalog.product",
                    ),
                ),
            ],
            options={
                "ordering": ["product__name_en", "id"],
                "base_manager_name": "objects",
                "default_manager_name": "objects",
                "indexes": [
                    models.Index(
                        fields=["organization", "asset"],
                        name="assets_org_asset_link_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("asset", "product"),
                        name="assets_unique_asset_product",
                    )
                ],
            },
        ),
    ]
