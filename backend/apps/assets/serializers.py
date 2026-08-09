import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Product

from .models import AssetProductLink, MaterialAsset, validate_metadata_json, validate_tags
from .services import upload_asset


class MultipartJSONField(serializers.JSONField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, RecursionError) as error:
                raise serializers.ValidationError("Enter valid JSON.") from error
        return super().to_internal_value(data)


class ProductAssetSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name_en", "status"]


class MaterialAssetSerializer(serializers.ModelSerializer):
    products = serializers.SerializerMethodField()

    @extend_schema_field(ProductAssetSummarySerializer(many=True))
    def get_products(self, asset: MaterialAsset) -> list[dict[str, object]]:
        links = getattr(asset, "safe_product_links", None)
        if links is None:
            links = AssetProductLink.objects.filter(
                asset=asset,
                organization=asset.organization,
                product__organization=asset.organization,
            ).select_related("product")
        products = [link.product for link in links]
        return ProductAssetSummarySerializer(products, many=True).data

    class Meta:
        model = MaterialAsset
        fields = [
            "id",
            "asset_type",
            "original_filename",
            "mime_type",
            "size_bytes",
            "checksum",
            "language",
            "status",
            "tags",
            "metadata_json",
            "created_by",
            "created_at",
            "updated_at",
            "products",
        ]
        read_only_fields = fields


class AssetUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    asset_type = serializers.ChoiceField(choices=MaterialAsset.AssetType.choices)
    language = serializers.CharField(max_length=16, allow_blank=True, default="")
    tags = MultipartJSONField(default=list)
    metadata_json = MultipartJSONField(default=dict)

    def validate_tags(self, value):
        try:
            validate_tags(value)
        except Exception as error:
            raise serializers.ValidationError(error.messages) from error
        return value

    def validate_metadata_json(self, value):
        try:
            validate_metadata_json(value)
        except Exception as error:
            raise serializers.ValidationError(error.messages) from error
        return value

    def create(self, validated_data):
        upload = validated_data.pop("file")
        return upload_asset(
            organization=self.context["organization"],
            creator=self.context["creator"],
            upload=upload,
            **validated_data,
        )


class AssetProductLinkInputSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()


class AssetFilterSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=MaterialAsset.AssetType.choices, required=False)
    status = serializers.ChoiceField(choices=MaterialAsset.Status.choices, required=False)
    product = serializers.UUIDField(required=False)
    tag = serializers.CharField(max_length=64, allow_blank=False, required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)
    cursor = serializers.CharField(required=False)


class AssetListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = MaterialAssetSerializer(many=True)


class AssetValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()


class AssetErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class AssetDownloadSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
