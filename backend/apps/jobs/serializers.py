from uuid import UUID

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Job


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class JobSourceReferenceSerializer(serializers.Serializer):
    brief_id = serializers.UUIDField(read_only=True)
    brief_version = serializers.IntegerField(min_value=1, read_only=True)


class JobSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="id", read_only=True)
    source_reference = serializers.SerializerMethodField()

    @extend_schema_field(JobSourceReferenceSerializer(allow_null=True))
    def get_source_reference(self, obj):
        if obj.type != Job.Type.CONTENT_GENERATE or not isinstance(obj.input_snapshot, dict):
            return None
        brief_id = obj.input_snapshot.get("brief_id")
        brief_version = obj.input_snapshot.get("brief_version")
        if not isinstance(brief_id, str) or type(brief_version) is not int or brief_version < 1:
            return None
        try:
            normalized_brief_id = str(UUID(brief_id))
        except (AttributeError, TypeError, ValueError):
            return None
        return {"brief_id": normalized_brief_id, "brief_version": brief_version}

    class Meta:
        model = Job
        fields = [
            "job_id", "type", "status", "progress", "attempt", "max_attempts",
            "created_at", "finished_at", "error", "result_reference", "source_reference",
        ]
        read_only_fields = fields


class JobListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = JobSerializer(many=True)


class JobFilterSerializer(StrictFieldsMixin, serializers.Serializer):
    type = serializers.ChoiceField(choices=Job.Type.choices, required=False)
    status = serializers.ChoiceField(choices=Job.Status.choices, required=False)
    job_id = serializers.UUIDField(required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class EmptyActionSerializer(StrictFieldsMixin, serializers.Serializer):
    pass


class JobErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


class JobConflictSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class JobValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
