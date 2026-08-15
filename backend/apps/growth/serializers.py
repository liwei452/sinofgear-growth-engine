from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from .models import (
    CRMHandoff,
    CandidateEnrichmentSnapshot,
    ChannelPackage,
    Contact,
    DiscoveryCandidate,
    FieldProvenance,
    FollowUp,
    GrowthPublishBatch,
    GrowthPublishItem,
    InboundLead,
    IntentSignal,
    MetricReceipt,
    OpportunityReview,
    OutreachDraft,
    TargetAccount,
)
from .manual_imports import validate_manual_source_url
from .enrichment import enrichment_payload


class PublishBatchCreateSerializer(serializers.Serializer):
    package_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False, max_length=8,
    )


class GrowthErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    recovery_action = serializers.CharField()


class GrowthValidationErrorSerializer(GrowthErrorSerializer):
    errors = serializers.DictField(required=False)


class DiscoveryProfileUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()


class DiscoveryRunResultSerializer(serializers.Serializer):
    status = serializers.CharField()
    finished_at = serializers.DateTimeField(allow_null=True)
    found_count = serializers.IntegerField()
    new_company_count = serializers.IntegerField()
    new_signal_count = serializers.IntegerField()
    duplicate_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    message = serializers.CharField()


class CandidateListImportSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=["CSV", "JSON"])
    content = serializers.CharField(min_length=2, max_length=1_000_000, trim_whitespace=False)
    source_owner = serializers.CharField(min_length=2, max_length=255)
    license_contract = serializers.CharField(min_length=2, max_length=255)
    retention_days = serializers.IntegerField(min_value=1, max_value=3650)
    redistribution_allowed = serializers.BooleanField()


class CandidateListImportResultSerializer(serializers.Serializer):
    created_count = serializers.IntegerField()
    duplicate_count = serializers.IntegerField()
    invalid_count = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField())
    queue_label = serializers.CharField()


class DiscoveryCandidateSerializer(serializers.ModelSerializer):
    status_label = serializers.SerializerMethodField()
    source_owner = serializers.SerializerMethodField()
    license_contract = serializers.SerializerMethodField()

    class Meta:
        model = DiscoveryCandidate
        fields = [
            "id", "company_name", "country", "website", "industry", "status",
            "status_label", "source_owner", "license_contract", "import_format",
            "is_demo", "created_at",
        ]

    def get_status_label(self, obj):
        return {
            DiscoveryCandidate.Status.PENDING_REVIEW: "待核实",
            DiscoveryCandidate.Status.ACCEPTED: "待补全公司资料",
            DiscoveryCandidate.Status.DISMISSED: "已忽略",
        }[obj.status]

    def get_source_owner(self, obj):
        return str(obj.source_governance.get("source_owner", ""))

    def get_license_contract(self, obj):
        return str(obj.source_governance.get("license_contract", ""))


class DiscoveryCandidateReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["ACCEPT", "DISMISS"])
    note = serializers.CharField(min_length=2, max_length=255)


class DiscoveryCandidateReviewResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    status_label = serializers.CharField()
    message = serializers.CharField()


class CandidateEnrichmentResultSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    mode = serializers.CharField()
    data_label = serializers.CharField()
    facts = serializers.ListField(child=serializers.DictField())
    public_contact_paths = serializers.ListField(child=serializers.DictField())
    uncertainties = serializers.ListField(child=serializers.CharField())
    message = serializers.CharField()
    created = serializers.BooleanField()


class EnrichmentCandidateSerializer(DiscoveryCandidateSerializer):
    latest_preview = serializers.SerializerMethodField()

    class Meta(DiscoveryCandidateSerializer.Meta):
        fields = [*DiscoveryCandidateSerializer.Meta.fields, "latest_preview"]

    def get_latest_preview(self, obj):
        try:
            snapshot = obj.enrichment_snapshot
        except CandidateEnrichmentSnapshot.DoesNotExist:
            return None
        return enrichment_payload(snapshot, created=False)


class DiscoverySummarySerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    source_label = serializers.CharField()
    schedule_label = serializers.CharField()
    product_scope_label = serializers.CharField()
    next_run_at = serializers.DateTimeField(allow_null=True)
    last_run = DiscoveryRunResultSerializer(allow_null=True)
    candidate_count = serializers.IntegerField()
    candidates = DiscoveryCandidateSerializer(many=True)
    enrichment_candidates = EnrichmentCandidateSerializer(many=True)
    available_sources = serializers.ListField(child=serializers.DictField())


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
    collection_method_label = serializers.SerializerMethodField()
    priority_label = serializers.SerializerMethodField()

    class Meta:
        model = IntentSignal
        fields = [
            "id", "account_id", "signal_type", "source_label", "source_url",
            "evidence_text", "confidence", "observed_at", "data_label",
            "collection_method", "collection_method_label", "content_hash",
            "score_breakdown", "scoring_rule_version", "uncertainty_notes",
            "evidence_envelope", "priority_label",
        ]

    def get_data_label(self, obj: IntentSignal) -> str:
        return "Demo / Fake" if obj.is_demo else "Licensed / permitted source"

    def get_collection_method_label(self, obj: IntentSignal) -> str:
        return {
            "DEMO_FIXTURE": "本地演示样本",
            "MANUAL_URL": "人工导入网页",
            "MANUAL_URL_WITH_SCREENSHOT": "人工导入网页与截图信息",
            "LICENSED_API": "许可数据接口",
            "INBOUND": "主动入站",
            "OFFICIAL_PUBLIC_API": "官方公开数据接口",
        }.get(obj.collection_method, "采集方式未说明")

    def get_priority_label(self, obj: IntentSignal) -> str:
        coverage = int((obj.score_breakdown or {}).get("evidence_coverage", 0))
        return "优先跟进" if obj.confidence >= 80 and coverage >= 15 else "继续观察"


class ManualOpportunityImportSerializer(serializers.Serializer):
    company_name = serializers.CharField(min_length=2, max_length=255)
    country = serializers.CharField(min_length=2, max_length=96)
    industry = serializers.CharField(max_length=160, allow_blank=True, required=False, default="")
    source_label = serializers.CharField(min_length=2, max_length=255)
    source_url = serializers.CharField(max_length=200)
    evidence_text = serializers.CharField(
        min_length=10,
        error_messages={"min_length": "原始证据至少需要 10 个字符。"},
    )
    screenshot_file_name = serializers.CharField(
        max_length=120, allow_blank=True, required=False, default="",
    )
    screenshot_captured_at = serializers.DateTimeField(
        allow_null=True, required=False, default=None,
    )

    def validate_source_url(self, value: str) -> str:
        try:
            return validate_manual_source_url(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message) from error

    def validate_screenshot_file_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        if "/" in value or "\\" in value or value in {".", ".."}:
            raise serializers.ValidationError("截图文件名不能包含路径。")
        if not value.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            raise serializers.ValidationError("截图文件仅支持 PNG、JPG、JPEG 或 WEBP。")
        return value

    def validate(self, attrs):
        file_name = attrs.get("screenshot_file_name", "")
        captured_at = attrs.get("screenshot_captured_at")
        if file_name and captured_at is None:
            raise serializers.ValidationError({"screenshot_captured_at": ["填写截图文件名时必须填写截图时间。"]})
        if captured_at is not None and not file_name:
            raise serializers.ValidationError({"screenshot_file_name": ["填写截图时间时必须填写截图文件名。"]})
        if captured_at is not None and captured_at > timezone.now():
            raise serializers.ValidationError({"screenshot_captured_at": ["截图时间不能晚于当前时间。"]})
        return attrs


class ManualOpportunityImportResponseSerializer(serializers.Serializer):
    account = TargetAccountSerializer()
    signal = IntentSignalSerializer()
    created = serializers.BooleanField()


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


class OpportunityReviewCreateSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=OpportunityReview.Decision.values)


class OpportunityReviewSerializer(serializers.ModelSerializer):
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = OpportunityReview
        fields = [
            "id", "account_id", "signal_id", "decision", "status_label", "reason",
            "original_confidence", "original_score_breakdown", "created_at",
        ]

    def get_status_label(self, obj: OpportunityReview) -> str:
        return {
            OpportunityReview.Decision.PRIORITIZE: "优先跟进",
            OpportunityReview.Decision.OBSERVE: "继续观察",
            OpportunityReview.Decision.PROCESSED: "已处理",
        }[obj.decision]


class CRMHandoffCreateSerializer(serializers.Serializer):
    draft_id = serializers.UUIDField()


class CRMHandoffSerializer(serializers.ModelSerializer):
    account_id = serializers.UUIDField(source="review.account_id", read_only=True)
    delivery = serializers.SerializerMethodField()

    class Meta:
        model = CRMHandoff
        fields = [
            "id", "account_id", "review_id", "draft_id", "connector", "status",
            "payload_snapshot", "delivery", "created_at",
        ]

    def get_delivery(self, _obj: CRMHandoff) -> str:
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
    OpportunityReview,
