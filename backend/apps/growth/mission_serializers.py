from rest_framework import serializers

from .mission_services import mission_lane_counts
from .models import GrowthMission, MissionPlan


class MissionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MissionPlan
        fields = [
            "id",
            "version",
            "status",
            "snapshot",
            "generation_mode",
            "provider",
            "model",
            "approved_by",
            "approved_at",
            "created_at",
        ]


class GrowthMissionSerializer(serializers.ModelSerializer):
    primary_product_id = serializers.UUIDField(read_only=True)
    latest_plan = serializers.SerializerMethodField()
    lane_counts = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()

    class Meta:
        model = GrowthMission
        fields = [
            "id",
            "title",
            "objective",
            "target_countries",
            "target_industries",
            "customer_profile",
            "primary_product_id",
            "start_date",
            "end_date",
            "target_account_count",
            "target_reply_count",
            "target_rfq_count",
            "budget_micros",
            "allowed_channels",
            "attribution_code",
            "status",
            "health_status",
            "health_reason",
            "created_by",
            "created_at",
            "latest_plan",
            "lane_counts",
            "available_actions",
        ]
        read_only_fields = [
            "id",
            "attribution_code",
            "status",
            "health_status",
            "health_reason",
            "created_by",
            "created_at",
        ]

    def get_latest_plan(self, obj):
        plan = obj.plans.order_by("-version").first()
        if plan is None:
            return None
        return MissionPlanSerializer(plan).data

    def get_lane_counts(self, obj):
        return mission_lane_counts(obj)

    def get_available_actions(self, obj):
        return self.context.get("available_actions", [])


class GrowthMissionInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    objective = serializers.CharField()
    target_countries = serializers.ListField(
        child=serializers.CharField(max_length=96), allow_empty=False
    )
    target_industries = serializers.ListField(
        child=serializers.CharField(max_length=160), allow_empty=False
    )
    customer_profile = serializers.CharField(required=False, allow_blank=True, default="")
    primary_product_id = serializers.UUIDField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    target_account_count = serializers.IntegerField(min_value=0, default=0)
    target_reply_count = serializers.IntegerField(min_value=0, default=0)
    target_rfq_count = serializers.IntegerField(min_value=0, default=0)
    budget_micros = serializers.IntegerField(min_value=0, default=0)
    allowed_channels = serializers.ListField(
        child=serializers.CharField(max_length=32), allow_empty=False
    )


class MissionStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=GrowthMission.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class MissionApprovePlanSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
