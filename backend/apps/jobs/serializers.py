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


class JobSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="id", read_only=True)
    generation_mode = serializers.SerializerMethodField()
    generation_label = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "job_id", "type", "status", "progress", "attempt", "max_attempts",
            "created_at", "finished_at", "error", "result_reference",
            "generation_mode", "generation_label",
        ]
        read_only_fields = fields

    @staticmethod
    def _provider(obj):
        runs = list(obj.ai_runs.all())
        if not runs:
            return ""
        return max(runs, key=lambda run: (run.job_attempt, run.created_at)).provider

    def get_generation_mode(self, obj):
        provider = self._provider(obj)
        if not provider:
            return "NOT_STARTED"
        return "FAKE_OFFLINE" if provider == "fake" else "CONFIGURED_AI"

    def get_generation_label(self, obj):
        return {
            "NOT_STARTED": "尚未启动生成服务",
            "FAKE_OFFLINE": "Fake / 离线演示生成",
            "CONFIGURED_AI": "已配置真实 AI 生成",
        }[self.get_generation_mode(obj)]


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
