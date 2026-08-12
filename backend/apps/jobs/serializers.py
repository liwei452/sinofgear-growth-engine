from uuid import UUID

from django.db.models import Q
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.ai.models import AIRun
from apps.common.security import public_error

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


class JobSerializerList(serializers.ListSerializer):
    def to_representation(self, data):
        items = list(data)
        latest = {}
        exact_runs = Q(pk__in=[])
        for item in items:
            exact_runs |= Q(
                job_id=item.id,
                organization_id=item.organization_id,
                job_attempt=item.attempt,
            )
        runs = AIRun.objects.filter(exact_runs).order_by("job_id", "-created_at", "-id")
        for run in runs:
            latest.setdefault(run.job_id, run)
        for item in items:
            item._public_ai_run = latest.get(item.id)
        return super().to_representation(items)


class JobSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="id", read_only=True)
    source_reference = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    retry_count = serializers.SerializerMethodField()
    next_retry_at = serializers.SerializerMethodField()

    def _latest_run(self, obj):
        if hasattr(obj, "_public_ai_run"):
            return obj._public_ai_run
        return obj.ai_runs.filter(
            organization_id=obj.organization_id, job_attempt=obj.attempt,
        ).order_by("-created_at", "-id").first()

    @extend_schema_field({"type": "object", "nullable": True})
    def get_error(self, obj):
        return public_error(obj.error)

    @extend_schema_field(serializers.IntegerField(min_value=0))
    def get_retry_count(self, obj):
        run = self._latest_run(obj)
        return run.transport_retry_count if run is not None else 0

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_next_retry_at(self, obj):
        run = self._latest_run(obj)
        retry_scheduled = (
            obj.status in {Job.Status.QUEUED, Job.Status.RUNNING, Job.Status.RETRY_QUEUED}
            and run is not None
            and run.status == AIRun.Status.RUNNING
            and run.transport_retry_count > 0
            and run.next_retry_at is not None
        )
        return run.next_retry_at if retry_scheduled else None

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
            "retry_count", "next_retry_at",
        ]
        read_only_fields = fields
        list_serializer_class = JobSerializerList


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
