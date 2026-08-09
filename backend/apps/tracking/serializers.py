from datetime import timedelta

from rest_framework import serializers

from .models import ShortLink, TrackingLink


class StrictMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({name: ["Unknown field."] for name in sorted(unknown)})
        return super().to_internal_value(data)


class TrackingLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackingLink
        fields = [
            "id", "destination", "full_url", "utm_source", "utm_medium", "utm_campaign",
            "utm_content", "utm_term", "campaign_id", "platform_id", "product_id",
            "published_post_id", "created_at",
        ]
        read_only_fields = fields


class TrackingLinkCreateSerializer(StrictMixin, serializers.Serializer):
    destination = serializers.CharField(max_length=2048)
    utm_source = serializers.CharField(max_length=128)
    utm_medium = serializers.CharField(max_length=128)
    utm_campaign = serializers.CharField(max_length=128)
    utm_content = serializers.CharField(max_length=128, required=False, allow_blank=False)
    utm_term = serializers.CharField(max_length=128, required=False, allow_blank=False)
    campaign_id = serializers.UUIDField()
    platform_id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    published_post_id = serializers.UUIDField()


class ShortLinkSerializer(serializers.ModelSerializer):
    redirect_path = serializers.SerializerMethodField()

    class Meta:
        model = ShortLink
        fields = ["id", "tracking_link_id", "code", "status", "redirect_path", "created_at", "updated_at"]
        read_only_fields = fields

    def get_redirect_path(self, short_link) -> str:
        return f"/r/{short_link.code}"


class ShortLinkCreateSerializer(StrictMixin, serializers.Serializer):
    tracking_link_id = serializers.UUIDField()


class CursorFilterSerializer(StrictMixin, serializers.Serializer):
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=50)


class AnalyticsFilterSerializer(StrictMixin, serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    campaign = serializers.UUIDField(required=False)
    platform = serializers.UUIDField(required=False)
    product = serializers.UUIDField(required=False)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    offset = serializers.IntegerField(required=False, min_value=0, default=0)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)

    def validate(self, attrs):
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError({"end": "End must be on or after start."})
        if attrs["end"] - attrs["start"] > timedelta(days=365):
            raise serializers.ValidationError({"end": "Analytics range is limited to 366 calendar days."})
        attrs["country"] = attrs.get("country", "").upper()
        if "page_size" in attrs:
            attrs["limit"] = attrs.pop("page_size")
        return attrs


class TrackingCursorEnvelopeSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = TrackingLinkSerializer(many=True)


class ShortCursorEnvelopeSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ShortLinkSerializer(many=True)


class ChannelSummaryRowSerializer(serializers.Serializer):
    date = serializers.DateField()
    campaign_id = serializers.UUIDField()
    platform_id = serializers.UUIDField()
    country = serializers.CharField(allow_blank=True, max_length=2)
    product_id = serializers.UUIDField()
    clicks = serializers.IntegerField(min_value=0)


class ChannelSummaryEnvelopeSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    total_clicks = serializers.IntegerField(min_value=0)
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = ChannelSummaryRowSerializer(many=True)


class TrackingErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class TrackingValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
