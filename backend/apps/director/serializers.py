from rest_framework import serializers

from .models import DirectorDecision, DirectorProposal


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class DirectorDecisionSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.ChoiceField(choices=DirectorProposal.ProposalType.choices)
    title = serializers.CharField()
    explanation = serializers.CharField()
    priority = serializers.IntegerField(min_value=1, max_value=100)
    version = serializers.IntegerField(min_value=1)
    actions = serializers.ListField(child=serializers.CharField())


class DirectorActiveWorkSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    label = serializers.CharField()
    status = serializers.CharField()
    progress = serializers.IntegerField(min_value=0, max_value=100)
    progress_is_determinate = serializers.BooleanField()


class DirectorOutcomeSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    value = serializers.CharField()
    detail = serializers.CharField()


class DirectorCockpitSerializer(serializers.Serializer):
    decisions = DirectorDecisionSummarySerializer(many=True)
    active_work = DirectorActiveWorkSerializer(many=True)
    recent_outcomes = DirectorOutcomeSerializer(many=True)
    generated_at = serializers.DateTimeField()


class DirectorDecisionRequestSerializer(StrictFieldsMixin, serializers.Serializer):
    action = serializers.ChoiceField(choices=DirectorDecision.Action.choices)
    expected_version = serializers.IntegerField(min_value=1)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class DirectorDecisionResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=DirectorProposal.Status.choices)
    version = serializers.IntegerField(min_value=1)


class DirectorConflictSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class DirectorReadErrorSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    recovery_action = serializers.CharField(required=False)


class DirectorValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
