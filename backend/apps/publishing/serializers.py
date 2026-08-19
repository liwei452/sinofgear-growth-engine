from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import PublishAttempt, PublishedPost, PublishTask
from .services import MAX_PUBLISH_ATTEMPTS


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


class PublishTaskSerializer(serializers.ModelSerializer):
    attempts = serializers.SerializerMethodField()
    published_post = serializers.SerializerMethodField()

    class Meta:
        model = PublishTask
        fields = [
            "id", "platform_content_id", "content_version", "social_account_id",
            "platform_id", "connector_code", "status", "scheduled_at",
            "requested_timezone", "attempt_number", "retry_not_before", "last_error",
            "provider_submission_id", "provider_call_started_at", "started_at",
            "finished_at", "canceled_at", "created_at", "attempts", "published_post",
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


class PublishCreateSerializer(StrictMixin, serializers.Serializer):
    platform_content_id = serializers.UUIDField()
    social_account_id = serializers.UUIDField()
    scheduled_at = AwareDateTimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, default="UTC", validators=[validate_timezone_name])


class EmptyActionSerializer(StrictMixin, serializers.Serializer):
    pass


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
