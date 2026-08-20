from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    PublishAttempt, PublishedPost, PublishReconciliationAttempt, PublishTask,
)
from .services import MAX_PUBLISH_ATTEMPTS
from .eligibility import publish_task_ui_contract


class StrictMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {name: ["Unknown field."] for name in sorted(unknown)}
            )
        return super().to_internal_value(data)


class AwareDateTimeField(serializers.DateTimeField):
    default_error_messages = {
        **serializers.DateTimeField.default_error_messages,
        "timezone": "Datetime must include an explicit UTC offset.",
    }

    def to_internal_value(self, value):
        parsed = value if isinstance(value, datetime) else parse_datetime(value)
        if parsed is not None and timezone.is_naive(parsed):
            self.fail("timezone")
        return super().to_internal_value(value)


class NativeStringField(serializers.CharField):
    def to_internal_value(self, data):
        if type(data) is not str:
            self.fail("invalid")
        return super().to_internal_value(data)


def validate_timezone_name(value):
    try:
        return ZoneInfo(value).key
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise serializers.ValidationError("Provide a valid IANA timezone.") from exc


class PublishAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublishAttempt
        fields = [
            "id", "number", "status", "outcome", "error", "retry_at",
            "external_id", "provider_submission_id", "provider_call_started_at",
            "started_at", "finished_at",
        ]
        read_only_fields = fields


class PublishedPostSerializer(serializers.ModelSerializer):
    type = serializers.CharField(default="published_post", read_only=True)

    class Meta:
        model = PublishedPost
        fields = ["type", "id", "external_id", "published_at"]
        read_only_fields = fields


class PublishReconciliationAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PublishReconciliationAttempt
        fields = [
            "id", "sequence_number", "mode", "provider",
            "provider_submission_id", "observed_provider_status", "result",
            "safe_error_code", "provider_post_id", "provider_channel_id",
            "provider_sent_at", "resolved_by_id", "started_at", "finished_at",
        ]
        read_only_fields = fields


class PublishActionEligibilitySerializer(serializers.Serializer):
    allowed = serializers.BooleanField(read_only=True)
    reason_code = serializers.CharField(read_only=True, allow_null=True)


class PublishAllowedActionsSerializer(serializers.Serializer):
    retry = PublishActionEligibilitySerializer(read_only=True)
    reconcile = PublishActionEligibilitySerializer(read_only=True)
    confirm_published = PublishActionEligibilitySerializer(read_only=True)
    confirm_not_published = PublishActionEligibilitySerializer(read_only=True)


class PublishResolutionEvidenceSerializer(serializers.Serializer):
    latest_outcome = serializers.CharField(read_only=True, allow_null=True)
    candidate_count = serializers.IntegerField(read_only=True, allow_null=True)
    query_window_end = serializers.DateTimeField(read_only=True, allow_null=True)
    query_window_ended = serializers.BooleanField(read_only=True)
    ambiguous = serializers.BooleanField(read_only=True)
    truncated = serializers.BooleanField(read_only=True)
    snapshot_valid = serializers.BooleanField(read_only=True)
    observed_at = serializers.DateTimeField(read_only=True, allow_null=True)


class PublishTaskSerializer(serializers.ModelSerializer):
    attempts = serializers.SerializerMethodField()
    published_post = serializers.SerializerMethodField()
    reconciliation_attempts = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()
    resolution_evidence = serializers.SerializerMethodField()

    class Meta:
        model = PublishTask
        fields = [
            "id", "platform_content_id", "content_version", "social_account_id",
            "platform_id", "connector_code", "status", "scheduled_at",
            "requested_timezone", "attempt_number", "retry_not_before", "last_error",
            "provider_submission_id", "provider_call_started_at", "started_at",
            "finished_at", "canceled_at", "created_at", "attempts", "published_post",
            "reconciliation_attempt_number", "last_reconciled_at", "next_reconcile_at",
            "reconciliation_error_code", "reconciliation_attempts",
            "allowed_actions", "resolution_evidence",
        ]
        read_only_fields = fields

    @extend_schema_field(PublishAttemptSerializer(many=True))
    def get_attempts(self, task):
        attempts = getattr(task, "_safe_attempts", None)
        if attempts is None:
            attempts = task.attempts.order_by("-number")[:MAX_PUBLISH_ATTEMPTS]
        attempts = sorted(attempts, key=lambda attempt: attempt.number)[
            -MAX_PUBLISH_ATTEMPTS:
        ]
        return PublishAttemptSerializer(attempts, many=True).data

    @extend_schema_field(PublishedPostSerializer(allow_null=True))
    def get_published_post(self, task):
        try:
            post = task.published_post
        except PublishedPost.DoesNotExist:
            return None
        return PublishedPostSerializer(post).data

    @extend_schema_field(PublishReconciliationAttemptSerializer(many=True))
    def get_reconciliation_attempts(self, task):
        attempts = getattr(task, "_safe_reconciliation_attempts", None)
        if attempts is None:
            attempts = task.reconciliation_attempts.order_by("-sequence_number")[:20]
        return PublishReconciliationAttemptSerializer(
            reversed(list(attempts)), many=True
        ).data

    def _ui_contract(self, task):
        if not hasattr(task, "_publish_ui_contract"):
            task._publish_ui_contract = publish_task_ui_contract(task)
        return task._publish_ui_contract

    @extend_schema_field(PublishAllowedActionsSerializer)
    def get_allowed_actions(self, task):
        return self._ui_contract(task)["allowed_actions"]

    @extend_schema_field(PublishResolutionEvidenceSerializer)
    def get_resolution_evidence(self, task):
        return self._ui_contract(task)["resolution_evidence"]


class PublishCreateSerializer(StrictMixin, serializers.Serializer):
    platform_content_id = serializers.UUIDField()
    social_account_id = serializers.UUIDField()
    scheduled_at = AwareDateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, default="UTC", validators=[validate_timezone_name])


class EmptyActionSerializer(StrictMixin, serializers.Serializer):
    pass


class PublishResolutionSerializer(StrictMixin, serializers.Serializer):
    resolution = serializers.ChoiceField(
        choices=["CONFIRM_PUBLISHED", "CONFIRM_NOT_PUBLISHED"]
    )
    provider_post_id = NativeStringField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=255,
    )

    def validate(self, attrs):
        resolution = attrs["resolution"]
        provider_post_id = attrs.get("provider_post_id", "")
        if resolution == "CONFIRM_PUBLISHED" and not provider_post_id:
            raise serializers.ValidationError(
                {"provider_post_id": "Buffer post ID is required."}
            )
        if resolution == "CONFIRM_NOT_PUBLISHED" and provider_post_id:
            raise serializers.ValidationError(
                {"provider_post_id": "Omit the post ID when confirming no post."}
            )
        return attrs


class ConfirmPublishedResolutionSerializer(StrictMixin, serializers.Serializer):
    resolution = serializers.ChoiceField(choices=["CONFIRM_PUBLISHED"])
    provider_post_id = NativeStringField(trim_whitespace=True, max_length=255)


class ConfirmNotPublishedResolutionSerializer(StrictMixin, serializers.Serializer):
    resolution = serializers.ChoiceField(choices=["CONFIRM_NOT_PUBLISHED"])


class PublishFilterSerializer(StrictMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=PublishTask.Status.choices, required=False)
    platform = serializers.UUIDField(required=False)
    account = serializers.UUIDField(required=False)
    content = serializers.UUIDField(required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50)


class CalendarFilterSerializer(StrictMixin, serializers.Serializer):
    start = AwareDateTimeField()
    end = AwareDateTimeField()
    timezone = serializers.CharField(validators=[validate_timezone_name])
    platform = serializers.UUIDField(required=False)
    account = serializers.UUIDField(required=False)
    product = serializers.UUIDField(required=False)
    campaign = serializers.UUIDField(required=False)
    country = serializers.CharField(required=False, max_length=128)
    status = serializers.ChoiceField(choices=PublishTask.Status.choices, required=False)

    def validate(self, attrs):
        if attrs["end"] <= attrs["start"]:
            raise serializers.ValidationError({"end": "End must be after start."})
        if attrs["end"] - attrs["start"] > timedelta(days=366):
            raise serializers.ValidationError({"end": "Calendar range is limited to 366 days."})
        return attrs


class PublishTaskCursorEnvelopeSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = PublishTaskSerializer(many=True)


class PublishCalendarMetadataSerializer(serializers.Serializer):
    max_entries = serializers.IntegerField(min_value=1)
    returned_entries = serializers.IntegerField(min_value=0)
    truncated = serializers.BooleanField()


class PublishCalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    entries = PublishTaskSerializer(many=True)


class PublishCalendarEnvelopeSerializer(serializers.Serializer):
    timezone = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    metadata = PublishCalendarMetadataSerializer()
    days = PublishCalendarDaySerializer(many=True)


class PublishingErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    recovery_action = serializers.CharField()
