from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.identity.permissions import PermissionCode
from apps.sources.models import SourceEvidence

from .models import LeadCandidate, LeadInsight, LeadReview


class StrictFieldsMixin:
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields) if hasattr(data, "keys") else set()
        errors = {name: ["Unknown field."] for name in sorted(unknown)}
        if hasattr(data, "getlist"):
            errors.update(
                {
                    name: ["Provide this field at most once."]
                    for name in self.fields
                    if len(data.getlist(name)) > 1
                }
            )
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class LeadCandidateCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    company_name = serializers.CharField(max_length=255, allow_blank=True, trim_whitespace=True)
    company_domain = serializers.CharField(
        max_length=512, required=False, allow_blank=True, trim_whitespace=True
    )
    country_hint = serializers.CharField(
        max_length=64, required=False, allow_blank=True, trim_whitespace=True
    )
    evidence_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=100, allow_empty=False
    )

    def validate_evidence_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Evidence IDs must be unique.")
        return value

    def create(self, validated_data):
        from .services import LeadService

        return LeadService.create_candidate(
            organization=self.context["organization"],
            creator=self.context["creator"],
            company_name=validated_data["company_name"],
            company_domain=validated_data.get("company_domain", ""),
            country_hint=validated_data.get("country_hint", ""),
            evidence_ids=validated_data["evidence_ids"],
        )


class LeadCandidateQuerySerializer(StrictFieldsMixin, serializers.Serializer):
    status = serializers.ChoiceField(choices=LeadCandidate.Status.choices, required=False)
    score_band = serializers.ChoiceField(choices=LeadInsight.ScoreBand.choices, required=False)
    minimum_score = serializers.IntegerField(min_value=0, max_value=100, required=False)
    platform = serializers.CharField(max_length=32, required=False)
    country = serializers.CharField(max_length=64, required=False)
    review_state = serializers.ChoiceField(
        choices=(("REVIEWED", "Reviewed"), ("UNREVIEWED", "Unreviewed")),
        required=False,
    )
    created_after = serializers.DateTimeField(required=False)
    created_before = serializers.DateTimeField(required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)

    def validate(self, attrs):
        if (
            attrs.get("created_after")
            and attrs.get("created_before")
            and attrs["created_after"] > attrs["created_before"]
        ):
            raise serializers.ValidationError(
                {"created_before": "Must be on or after created_after."}
            )
        return attrs


class LeadAnalyzeRequestSerializer(StrictFieldsMixin, serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    evidence_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=100, allow_empty=False
    )
    idempotency_key = serializers.CharField(
        max_length=128, allow_blank=False, trim_whitespace=True
    )
    enhanced_analysis = serializers.BooleanField(required=False, default=False)

    def validate_evidence_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Evidence IDs must be unique.")
        return value


class LeadReviewCreateSerializer(StrictFieldsMixin, serializers.Serializer):
    candidate_id = serializers.UUIDField()
    action = serializers.ChoiceField(
        choices=[*LeadReview.Action.choices, ("MERGE_COMPANY", "Merge company"), ("SPLIT_COMPANY", "Split company")]
    )
    expected_version = serializers.IntegerField(min_value=1)
    correction = serializers.JSONField(required=False, allow_null=True)
    reason = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)
    idempotency_key = serializers.CharField(
        max_length=128, allow_blank=False, trim_whitespace=True
    )

    def validate(self, attrs):
        correction = attrs.get("correction")
        if attrs["action"] == LeadReview.Action.CORRECT and not isinstance(correction, dict):
            raise serializers.ValidationError(
                {"correction": "Correction details are required for CORRECT."}
            )
        if attrs["action"] != LeadReview.Action.CORRECT and correction is not None:
            raise serializers.ValidationError(
                {"correction": "Only CORRECT accepts correction details."}
            )
        return attrs


class LeadEvidenceSummarySerializer(serializers.ModelSerializer):
    source_signal_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SourceEvidence
        fields = [
            "id",
            "source_signal_id",
            "original_text",
            "translated_text",
            "source_url",
            "platform",
            "public_published_at",
            "captured_at",
            "collection_method",
            "language",
            "availability",
            "retention_class",
        ]
        read_only_fields = fields


class LeadInsightSummarySerializer(serializers.ModelSerializer):
    dimensions = serializers.SerializerMethodField()
    gates = serializers.SerializerMethodField()
    ai_audit = serializers.SerializerMethodField()
    source_insight_id = serializers.UUIDField(read_only=True, allow_null=True)

    @extend_schema_field(serializers.DictField())
    def get_dimensions(self, insight):
        return {
            "intent": insight.intent_score,
            "company_fit": insight.company_fit_score,
            "specificity": insight.specificity_score,
            "capability_fit": insight.capability_fit_score,
            "recency": insight.recency_score,
        }

    @extend_schema_field(serializers.DictField())
    def get_gates(self, insight):
        return {
            "traceable_source": insight.traceable_source,
            "explicit_need_or_company_match": insight.explicit_need_or_company_match,
            "capability_evidence": insight.capability_evidence,
            "audited_run": insight.audited_run,
            "ontology_snapshot": insight.ontology_snapshot_complete,
        }

    @extend_schema_field(serializers.DictField())
    def get_ai_audit(self, insight):
        run = insight.ai_run
        prompt = run.prompt_version
        return {
            "ai_run_id": str(run.id),
            "status": run.status,
            "prompt_code": prompt.code,
            "prompt_version": prompt.version,
            "model": run.model,
        }

    class Meta:
        model = LeadInsight
        fields = [
            "id",
            "version",
            "origin",
            "source_insight_id",
            "score",
            "score_band",
            "high_value_eligible",
            "dimensions",
            "gates",
            "explanation",
            "extracted_requirement_values",
            "evidence_confidence",
            "company_match_confidence",
            "ai_confidence",
            "human_correction",
            "reviewed_by",
            "reviewed_at",
            "review_reason",
            "ai_audit",
            "created_at",
        ]
        read_only_fields = fields


class LeadRequirementSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    requirement_code = serializers.CharField()
    requirement_label = serializers.CharField()
    capability_code = serializers.CharField(allow_null=True)
    capability_label = serializers.CharField(allow_null=True)
    capability_knowledge_evidence_id = serializers.UUIDField(allow_null=True)
    source_evidence_id = serializers.UUIDField()
    extracted_value = serializers.CharField()
    unit = serializers.CharField()


class LeadReviewSerializer(serializers.ModelSerializer):
    insight_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = LeadReview
        fields = [
            "id",
            "action",
            "reason",
            "correction",
            "reviewer",
            "insight_id",
            "candidate_status",
            "candidate_version",
            "created_at",
        ]
        read_only_fields = fields


class LeadCandidateListSerializer(serializers.ModelSerializer):
    latest_score = serializers.IntegerField(source="latest_insight.score", allow_null=True)
    latest_score_band = serializers.CharField(
        source="latest_insight.score_band", allow_null=True
    )
    high_value_eligible = serializers.BooleanField(
        source="latest_insight.high_value_eligible", allow_null=True
    )

    class Meta:
        model = LeadCandidate
        fields = [
            "id",
            "company_name",
            "company_domain",
            "country_hint",
            "status",
            "version",
            "latest_score",
            "latest_score_band",
            "high_value_eligible",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class LeadCandidateDetailSerializer(serializers.ModelSerializer):
    company = serializers.SerializerMethodField()
    latest_insight = LeadInsightSummarySerializer(read_only=True)
    evidence = serializers.SerializerMethodField()
    requirements = serializers.SerializerMethodField()
    insight_history = serializers.SerializerMethodField()
    review_history = serializers.SerializerMethodField()
    permitted_actions = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField())
    def get_company(self, candidate):
        return {
            "name": candidate.company_name,
            "domain": candidate.company_domain,
            "country_hint": candidate.country_hint,
        }

    @extend_schema_field(LeadEvidenceSummarySerializer(many=True))
    def get_evidence(self, candidate):
        rows = getattr(candidate, "detail_evidence", [])
        return LeadEvidenceSummarySerializer(rows, many=True).data

    @extend_schema_field(LeadRequirementSerializer(many=True))
    def get_requirements(self, candidate):
        insight = candidate.latest_insight
        if insight is None:
            return []
        history_insight = next(
            (
                row
                for row in getattr(candidate, "detail_insights", [])
                if row.id == insight.id
            ),
            insight,
        )
        rows = getattr(history_insight, "detail_requirements", [])
        return [
            {
                "id": row.id,
                "requirement_code": row.requirement_concept.code,
                "requirement_label": row.requirement_concept.label_zh
                or row.requirement_concept.label_en,
                "capability_code": (
                    row.capability_concept.code if row.capability_concept else None
                ),
                "capability_label": (
                    row.capability_concept.label_zh
                    or row.capability_concept.label_en
                    if row.capability_concept
                    else None
                ),
                "capability_knowledge_evidence_id": (
                    row.capability_knowledge_evidence_id
                ),
                "source_evidence_id": row.source_evidence_id,
                "extracted_value": row.extracted_value,
                "unit": row.unit,
            }
            for row in rows
        ]

    @extend_schema_field(LeadInsightSummarySerializer(many=True))
    def get_insight_history(self, candidate):
        return LeadInsightSummarySerializer(
            getattr(candidate, "detail_insights", []), many=True
        ).data

    @extend_schema_field(LeadReviewSerializer(many=True))
    def get_review_history(self, candidate):
        return LeadReviewSerializer(
            getattr(candidate, "detail_reviews", []), many=True
        ).data

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_permitted_actions(self, candidate):
        request = self.context.get("request")
        membership = getattr(request, "membership", None)
        if (
            membership is None
            or membership.organization_id != candidate.organization_id
        ):
            return []
        permissions = set(membership.role.permissions)
        can_analyze = PermissionCode.LEADS_ANALYZE.value in permissions
        can_review = PermissionCode.LEADS_REVIEW.value in permissions
        actions = []
        if candidate.status == LeadCandidate.Status.ANALYZED:
            if can_analyze:
                actions.append("ANALYZE")
            if can_review:
                actions.extend(
                    ["CONFIRM", "CORRECT", "DISMISS", "REQUEST_MORE_EVIDENCE"]
                )
        elif candidate.status == LeadCandidate.Status.DISCOVERED and can_analyze:
            actions.append("ANALYZE")
        elif candidate.status == LeadCandidate.Status.REVIEWED and can_review:
            actions.extend(["DISMISS", "REQUEST_MORE_EVIDENCE"])
        elif candidate.status == LeadCandidate.Status.DISMISSED and can_review:
            actions.append("REOPEN")
        return actions

    class Meta:
        model = LeadCandidate
        fields = [
            "id",
            "company",
            "status",
            "version",
            "latest_insight",
            "evidence",
            "requirements",
            "insight_history",
            "review_history",
            "permitted_actions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class LeadCandidatePageSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = LeadCandidateListSerializer(many=True)


class LeadInsightQuerySerializer(StrictFieldsMixin, serializers.Serializer):
    candidate_id = serializers.UUIDField(required=False)
    cursor = serializers.CharField(required=False)
    page_size = serializers.IntegerField(min_value=1, max_value=50, required=False)


class LeadInsightPageSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = LeadInsightSummarySerializer(many=True)


class LeadAnalyzeAcceptedSerializer(serializers.Serializer):
    job_id = serializers.UUIDField()
    lead_candidate_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RETRY_QUEUED", "CANCELED"))


class LeadReviewResultSerializer(serializers.Serializer):
    review_id = serializers.UUIDField()
    lead_candidate_id = serializers.UUIDField()
    candidate_status = serializers.ChoiceField(choices=LeadCandidate.Status.choices)
    candidate_version = serializers.IntegerField()
    insight_id = serializers.UUIDField(allow_null=True)
    insight_version = serializers.IntegerField(allow_null=True)


class LeadMutationErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    recovery_action = serializers.CharField()
    detail = serializers.CharField(required=False)
    errors = serializers.DictField(required=False)


class LeadReadErrorSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    recovery_action = serializers.CharField(required=False)


class LeadValidationErrorSerializer(serializers.Serializer):
    errors = serializers.DictField()
    code = serializers.CharField()
    message = serializers.CharField()
    recovery_action = serializers.CharField()
