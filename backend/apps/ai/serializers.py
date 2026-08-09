from rest_framework import serializers

from apps.common.security import scrub_secrets

from .models import AIRun


class AIRunSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(read_only=True)
    prompt = serializers.SerializerMethodField()
    reviewer = serializers.SerializerMethodField()
    input_snapshot = serializers.SerializerMethodField()
    output_json = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()
    provider_metadata = serializers.SerializerMethodField()
    human_correction = serializers.SerializerMethodField()

    class Meta:
        model = AIRun
        fields = [
            "id", "job_id", "job_attempt", "status", "prompt", "provider", "model",
            "confidence", "human_correction", "reviewer", "created_at", "started_at",
            "finished_at", "reviewed_at", "input_snapshot", "output_json", "error",
            "provider_metadata",
        ]
        read_only_fields = fields

    def get_prompt(self, run: AIRun) -> dict[str, object]:
        prompt = run.prompt_version
        return {
            "purpose": prompt.purpose,
            "code": prompt.code,
            "version": prompt.version,
            "provider": prompt.provider,
            "model": prompt.model,
        }

    def get_reviewer(self, run: AIRun) -> dict[str, object] | None:
        if run.reviewed_by_id is None:
            return None
        return {"id": run.reviewed_by_id, "username": run.reviewed_by.get_username()}

    def _safe(self, value):
        return scrub_secrets(value)

    def get_input_snapshot(self, run: AIRun):
        return self._safe(run.input_snapshot)

    def get_output_json(self, run: AIRun):
        return self._safe(run.output_json)

    def get_error(self, run: AIRun):
        return self._safe(run.error)

    def get_provider_metadata(self, run: AIRun):
        return self._safe(run.provider_metadata)

    def get_human_correction(self, run: AIRun):
        return self._safe(run.human_correction)


class AIRunListSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AIRunSerializer(many=True)


class AIRunFilterSerializer(serializers.Serializer):
    job = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=AIRun.Status.choices, required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class AIRunValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
