from rest_framework import serializers

from .models import (
    ChannelPackage,
    Contact,
    FieldProvenance,
    FollowUp,
    GrowthPublishBatch,
    GrowthPublishItem,
    InboundLead,
    IntentSignal,
    MetricReceipt,
    OutreachDraft,
    TargetAccount,
)


class PublishBatchCreateSerializer(serializers.Serializer):
    package_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=8,
    )


class GrowthPublishItemSerializer(serializers.ModelSerializer):
    error_code = serializers.SerializerMethodField()
    recovery_action = serializers.SerializerMethodField()
    mode = serializers.SerializerMethodField()
    retryable = serializers.SerializerMethodField()

    class Meta:
        model = GrowthPublishItem
        fields = [
            "id", "channel", "status", "attempt_number", "external_post_url",
            "mode", "error_code", "retryable", "recovery_action", "created_at", "updated_at",
        ]

    def get_mode(self, obj: GrowthPublishItem) -> str:
        return "DEMO_FAKE" if obj.channel_package.is_demo else "OFFICIAL"

    def get_retryable(self, obj: GrowthPublishItem) -> bool:
        return bool((obj.last_error or {}).get("retryable", False))

    def get_error_code(self, obj: GrowthPublishItem) -> str:
        return str((obj.last_error or {}).get("code", ""))

    def get_recovery_action(self, obj: GrowthPublishItem) -> str:
        return {
            "CONFIGURATION_REQUIRED": "完成官方平台配置后再发布。",
            "CONNECTOR_MODE_MISMATCH": "请选择与内容类型匹配的发布连接。",
            "PROVIDER_UNAVAILABLE": "平台暂时不可用，请稍后重试。",
            "REAUTHORIZATION_REQUIRED": "请重新连接账号。",
            "VALIDATION_REJECTED": "请检查该渠道内容后重试。",
            "OUTCOME_UNKNOWN": "系统核对发布结果后再重试。",
            "CONTENT_NOT_APPROVED": "请先审核该渠道内容。",
            "ACCOUNT_NOT_CONNECTED": "连接账号后可发布。",
            "PROVIDER_ERROR": "可重试该失败渠道。",
            "RATE_LIMITED": "平台繁忙，请稍后重试。",
            "TOKEN_EXPIRED": "请重新连接账号。",
        }.get(self.get_error_code(obj), "")


class GrowthPublishBatchSerializer(serializers.ModelSerializer):
    items = GrowthPublishItemSerializer(many=True, read_only=True)
    data_label = serializers.SerializerMethodField()

    class Meta:
        model = GrowthPublishBatch
        fields = [
            "id", "status", "is_demo", "data_label", "created_at", "updated_at", "items",
        ]

    def get_data_label(self, obj: GrowthPublishBatch) -> str:
        return "Demo / Fake 发布结果" if obj.is_demo else "真实平台发布结果"


class TargetAccountSerializer(serializers.ModelSerializer):
    data_label = serializers.SerializerMethodField()

    class Meta:
        model = TargetAccount
        fields = ["id", "name", "country", "industry", "employee_range", "website", "is_demo", "data_label"]

    def get_data_label(self, obj: TargetAccount) -> str:
        return "Demo / Fake" if obj.is_demo else "Licensed / permitted source"


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "account_id", "full_name", "role_title", "public_contact_path", "verification_status"]


class IntentSignalSerializer(serializers.ModelSerializer):
    data_label = serializers.SerializerMethodField()

    class Meta:
        model = IntentSignal
        fields = ["id", "account_id", "signal_type", "source_label", "source_url", "evidence_text", "confidence", "observed_at", "data_label"]

    def get_data_label(self, obj: IntentSignal) -> str:
        return "Demo / Fake" if obj.is_demo else "Licensed / permitted source"


class InboundLeadSerializer(serializers.ModelSerializer):
    data_label = serializers.SerializerMethodField()

    class Meta:
        model = InboundLead
        fields = ["id", "account_id", "source_label", "status", "data_label"]

    def get_data_label(self, obj: InboundLead) -> str:
        return "Demo / Fake" if obj.is_demo else "Confirmed inbound"


class FollowUpSerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowUp
        fields = ["id", "account_id", "status", "created_at", "updated_at"]


class OutreachDraftSerializer(serializers.ModelSerializer):
    delivery = serializers.SerializerMethodField()

    class Meta:
        model = OutreachDraft
        fields = [
            "id", "account_id", "english_draft", "chinese_explanation", "status",
            "delivery", "created_at", "updated_at",
        ]

    def get_delivery(self, _obj: OutreachDraft) -> str:
        return "NEVER_SENT"


class ChannelPackageSerializer(serializers.ModelSerializer):
    data_label = serializers.SerializerMethodField()
    delivery = serializers.SerializerMethodField()

    class Meta:
        model = ChannelPackage
        fields = [
            "id", "account_id", "channel", "payload", "status", "is_demo",
            "data_label", "delivery", "created_at", "updated_at",
        ]

    def get_data_label(self, obj: ChannelPackage) -> str:
        return "Demo / Fake" if obj.is_demo else "Reviewed content package"

    def get_delivery(self, _obj: ChannelPackage) -> str:
        return "MANUAL_ONLY"


class MetricReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricReceipt
        fields = ["id", "channel", "payload", "is_demo", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metrics must be a JSON object.")
        return value


class FieldProvenanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldProvenance
        fields = [
            "id", "field_name", "field_value", "source_label", "verification_status",
            "source_cost_micros", "created_at", "updated_at",
        ]
