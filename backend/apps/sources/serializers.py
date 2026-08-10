from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .importers import SUPPORTED_SOURCE_TYPES, prepare_import_reference
from .models import (
    IngestionBatch,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields) if hasattr(data, "keys") else set()
        errors = {name: ["Unknown field."] for name in sorted(unknown)}
        if hasattr(data, "getlist"):
            errors.update(
                {
                    name: ["Provide this field at most once."]
                    for name in self.fields
                    if len(data.getlist(name)) > 1
                }
            )
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class MonitoringTargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitoringTarget
        fields = [
            "id",
            "target_type",
            "collection_mode",
            "platform",
            "external_reference",
            "normalized_url",
            "label",
            "schedule",
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]


class MonitoringTargetCreateSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = MonitoringTarget
        fields = [
            "target_type",
            "collection_mode",
            "platform",
            "external_reference",
            "normalized_url",
            "label",
            "schedule",
            "enabled",
        ]
        extra_kwargs = {
            "external_reference": {"required": False},
            "normalized_url": {"required": False},
            "schedule": {"required": False},
            "enabled": {"required": False},
        }

    def create(self, validated_data):
        return MonitoringTarget.objects.create(
            organization=self.context["organization"],
            created_by=self.context["creator"],
            **validated_data,
        )


class IngestionBatchSerializer(serializers.ModelSerializer):
    monitoring_target_id = serializers.UUIDField(read_only=True, allow_null=True)
    job_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = IngestionBatch
        fields = [
            "id",
            "source_type",
            "status",
            "monitoring_target_id",
            "job_id",
            "received_count",
            "accepted_count",
            "duplicate_count",
            "failed_count",
            "row_errors",
            "idempotency_key",
            "started_at",
            "finished_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class IngestionBatchCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    source_type = serializers.ChoiceField(
        choices=sorted((str(value), str(value)) for value in SUPPORTED_SOURCE_TYPES)
    )
    monitoring_target_id = serializers.UUIDField(required=False, allow_null=True)
    import_asset_id = serializers.UUIDField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(max_length=128, allow_blank=False, trim_whitespace=True)
    payload = serializers.JSONField()

    def validate(self, attrs):
        raw_payload = attrs.pop("payload")
        prepared_reference = prepare_import_reference(
            raw_payload, source_type=attrs["source_type"]
        )
        if "import_asset_id" in prepared_reference:
            raise serializers.ValidationError(
                {
                    "payload": [
                        "Provide import_asset_id only in the top-level request field."
                    ]
                }
            )
        attrs["prepared_reference"] = prepared_reference
        return attrs

    def create(self, validated_data):
        from .services import SourceIngestionRequestService

        return SourceIngestionRequestService.create_or_reuse(
            organization=self.context["organization"],
            creator=self.context["creator"],
            **validated_data,
        )


class IngestionAcceptedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    ingestion_batch_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=IngestionBatch.Status.choices)


class SourceContentSerializer(serializers.ModelSerializer):
    monitoring_target_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = SourceContent
        fields = [
            "id",
            "monitoring_target_id",
            "platform",
            "external_id",
            "canonical_url",
            "author_public_name",
            "title",
            "original_text",
            "public_published_at",
            "language",
            "captured_at",
            "content_hash",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SourceSignalSerializer(serializers.ModelSerializer):
    monitoring_target_id = serializers.UUIDField(read_only=True, allow_null=True)
    source_content_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = SourceSignal
        fields = [
            "id",
            "monitoring_target_id",
            "source_content_id",
            "signal_type",
            "platform",
            "external_id",
            "captured_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SourceEvidenceSerializer(serializers.ModelSerializer):
    source_signal_id = serializers.UUIDField(read_only=True)
    screenshot_download_endpoint = serializers.SerializerMethodField()
    import_download_endpoint = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_screenshot_download_endpoint(self, evidence):
        return self._download_endpoint(evidence.screenshot_asset_id)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_import_download_endpoint(self, evidence):
        return self._download_endpoint(evidence.import_asset_id)

    @staticmethod
    def _download_endpoint(asset_id):
        if asset_id is None:
            return None
        return f"/api/v1/assets/{asset_id}/download-url"

    class Meta:
        model = SourceEvidence
        fields = [
            "id",
            "source_signal_id",
            "evidence_type",
            "original_text",
            "translated_text",
            "translated_language",
            "source_url",
            "platform",
            "public_published_at",
            "captured_at",
            "collection_method",
            "language",
            "content_hash",
            "availability",
            "retention_class",
            "screenshot_download_endpoint",
            "import_download_endpoint",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PageQuerySerializer(StrictFieldsMixin, serializers.Serializer):
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class MonitoringTargetListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = MonitoringTargetSerializer(many=True)


class IngestionBatchListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = IngestionBatchSerializer(many=True)


class SourceContentListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SourceContentSerializer(many=True)


class SourceSignalListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SourceSignalSerializer(many=True)


class SourceEvidenceListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SourceEvidenceSerializer(many=True)


class SourceValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
    code = serializers.CharField()
    message = serializers.CharField()
    recovery_action = serializers.CharField()


class SourceErrorSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    recovery_action = serializers.CharField(required=False)
