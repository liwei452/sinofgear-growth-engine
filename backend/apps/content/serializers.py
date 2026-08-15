from drf_spectacular.utils import OpenApiTypes, extend_schema_field
from rest_framework import serializers

from .models import MasterContent, PlatformContent
from .payloads import validate_content_payload


class StrictMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class MasterContentSerializer(serializers.ModelSerializer):
    is_current_head = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_current_head(self, content):
        annotated = getattr(content, "_is_current_head", None)
        if annotated is not None:
            return annotated
        return not MasterContent.objects.filter(
            organization_id=content.organization_id,
            lineage_id=content.lineage_id,
            previous_version_id=content.id,
        ).exists()

    class Meta:
        model = MasterContent
        fields = [
            "id", "brief_id", "brief_version", "generation_job_id", "ai_run_id",
            "lineage_id", "previous_version_id", "version", "payload", "provenance",
            "status", "is_current_head", "created_by_id", "created_at", "updated_at",
        ]


class PlatformContentSerializer(serializers.ModelSerializer):
    is_current_head = serializers.SerializerMethodField()
    publish_package_id = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_current_head(self, content):
        annotated = getattr(content, "_is_current_head", None)
        if annotated is not None:
            return annotated
        return not PlatformContent.objects.filter(
            organization_id=content.organization_id,
            lineage_id=content.lineage_id,
            previous_version_id=content.id,
        ).exists()

    @extend_schema_field({"type": "string", "format": "uuid", "nullable": True})
    def get_publish_package_id(self, content):
        package = getattr(content, "growth_channel_package", None)
        return package.id if package is not None else None

    class Meta:
        model = PlatformContent
        fields = [
            "id", "master_content_id", "master_version", "platform_id", "lineage_id",
            "previous_version_id", "version", "payload", "provenance", "status",
            "is_current_head", "publish_package_id",
            "created_by_id", "created_at", "updated_at",
        ]


class BaseRevisionSerializer(StrictMixin, serializers.Serializer):
    payload = serializers.JSONField()


class MasterRevisionSerializer(BaseRevisionSerializer):
    def validate_payload(self, value):
        try:
            return validate_content_payload(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class PlatformRevisionSerializer(BaseRevisionSerializer):
    def validate_payload(self, value):
        try:
            platform_code = value.get("platform_code") if isinstance(value, dict) else None
            if platform_code is None:
                raise ValueError("Platform content payload requires platform_code.")
            return validate_content_payload(value, platform_code=platform_code)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ReviewSerializer(StrictMixin, serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class PlatformGenerationSerializer(StrictMixin, serializers.Serializer):
    platform_id = serializers.UUIDField()


class EmptySerializer(StrictMixin, serializers.Serializer):
    pass


class JobAcceptedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    status = serializers.CharField()


class ContentFilterSerializer(StrictMixin, serializers.Serializer):
    status = serializers.CharField(required=False)
    brief = serializers.UUIDField(required=False)
    campaign = serializers.UUIDField(required=False)
    product = serializers.UUIDField(required=False)
    platform = serializers.UUIDField(required=False)
    lineage = serializers.UUIDField(required=False)
    version = serializers.IntegerField(required=False, min_value=1)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50)
