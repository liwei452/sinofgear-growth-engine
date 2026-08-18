"""HTTP endpoints for inspecting and approving agent runs."""

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import (
    CanManageCampaigns,
    CanReadCampaigns,
    PermissionCode,
)
from apps.identity.services import get_active_membership, require_permission

from .agent.resume import resume_agent_run
from .agent.execution import PlannerConfigurationUnavailable
from .agent.content_creation_tools import (
    run_content_creation_agent,
    run_platform_variants_agent,
)
from .agent.content_tools import run_content_strategy_agent
from .agent.publishing_tools import run_social_ops_agent
from .growth_events import mark_events_published
from .mission_services import link_mission_entity, sync_mission_links_from_agent_run
from .models import AgentRun, AgentRunStep, GrowthEvent, GrowthMission, MissionEntityLink


AGENT_PERMISSIONS = {
    "content_strategy": "campaigns.manage",
    "content_creation": "content.manage",
    "platform_variants": "content.manage",
    "social_ops": "publishing.manage",
}

TOOL_PERMISSIONS = {
    "create_content_brief": "campaigns.manage",
    "enrich_content_brief": "content.manage",
    "mark_content_brief_ready": "content.review",
    "trigger_master_generation": "content.manage",
    "create_platform_variants": "content.manage",
    "schedule_social_post": "publishing.manage",
    "send_email": "leads.manage",
}


def _require(request, permission: str) -> None:
    require_permission(
        membership=get_active_membership(user=request.user),
        permission=permission,
    )


class AgentRunStepSerializer(serializers.ModelSerializer):
    executed_by = serializers.SerializerMethodField()

    class Meta:
        model = AgentRunStep
        fields = [
            "index",
            "tool_name",
            "args",
            "outcome",
            "output",
            "error",
            "reasoning",
            "executed_by",
        ]

    def get_executed_by(self, obj: AgentRunStep):
        user = obj.executed_by
        return {"id": user.id, "username": user.username} if user else None


class AgentRunSerializer(serializers.ModelSerializer):
    steps = AgentRunStepSerializer(many=True, read_only=True)
    pending_approval = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()
    rejected_by = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(read_only=True)
    rejected_at = serializers.DateTimeField(read_only=True)
    approval_comment = serializers.CharField(read_only=True)

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "goal",
            "agent_type",
            "execution_mode",
            "planner_provider",
            "planner_model",
            "status",
            "terminal_reason",
            "created_at",
            "updated_at",
            "created_by",
            "approved_by",
            "rejected_by",
            "approved_at",
            "rejected_at",
            "approval_comment",
            "steps",
            "pending_approval",
        ]

    def get_created_by(self, obj: AgentRun):
        return {"id": obj.created_by.id, "username": obj.created_by.username} if obj.created_by else None

    def get_approved_by(self, obj: AgentRun):
        return {"id": obj.approved_by.id, "username": obj.approved_by.username} if obj.approved_by else None

    def get_rejected_by(self, obj: AgentRun):
        return {"id": obj.rejected_by.id, "username": obj.rejected_by.username} if obj.rejected_by else None

    def get_pending_approval(self, obj: AgentRun) -> dict | None:
        step = obj.steps.filter(outcome="blocked_approval").order_by("-index", "-id").first()
        if step is None:
            return None
        return {
            "tool_name": step.tool_name,
            "tool_args": step.args,
            "reasoning": step.reasoning,
        }


class AgentRunStartSerializer(serializers.Serializer):
    agent_type = serializers.ChoiceField(choices=list(AGENT_PERMISSIONS.keys()))
    brief_id = serializers.UUIDField(required=False)
    product_id = serializers.UUIDField(required=False)
    platform_id = serializers.UUIDField(required=False)
    master_id = serializers.UUIDField(required=False)
    content_id = serializers.UUIDField(required=False)
    account_id = serializers.UUIDField(required=False)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)
    timezone_name = serializers.CharField(required=False, default="UTC")
    values = serializers.DictField(required=False)
    asset_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    mission_id = serializers.UUIDField(required=False)


class AgentRunStartResultSerializer(serializers.Serializer):
    status = serializers.CharField()
    terminal_reason = serializers.CharField(allow_null=True)
    pending_approval_token = serializers.CharField(allow_null=True)


class AgentRunApproveSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=["approve", "reject"], required=False, default="approve",
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class AgentRunListView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(
        tags=["Agent"],
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                enum=AgentRun.Status.values,
                required=False,
            ),
        ],
        responses={200: AgentRunSerializer(many=True)},
    )
    def get(self, request):
        runs = AgentRun.objects.filter(organization=request.organization).order_by(
            "-created_at", "-id",
        )
        status = request.query_params.get("status")
        if status:
            runs = runs.filter(status=status)
        return Response(AgentRunSerializer(runs, many=True).data)


class AgentRunDetailView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Agent"], responses={200: AgentRunSerializer})
    def get(self, request, run_id):
        run = get_object_or_404(AgentRun, id=run_id, organization=request.organization)
        return Response(AgentRunSerializer(run).data)


class AgentRunApproveView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(
        tags=["Agent"],
        request=AgentRunApproveSerializer,
        responses={200: AgentRunSerializer},
    )
    def post(self, request, run_id):
        run = get_object_or_404(AgentRun, id=run_id, organization=request.organization)
        if run.status != AgentRun.Status.WAITING_APPROVAL:
            return Response({"message": "Run is not waiting for approval."}, status=409)
        _require(request, PermissionCode.AGENTS_APPROVE)

        serializer = AgentRunApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data["decision"]
        comment = str(serializer.validated_data.get("comment") or "").strip()
        now = timezone.now()
        if decision == "reject":
            run.status = AgentRun.Status.REJECTED
            run.terminal_reason = "Rejected by reviewer."
            run.rejected_by = request.user
            run.rejected_at = now
            run.approval_comment = comment
            run.save(update_fields=[
                "status", "terminal_reason", "rejected_by",
                "rejected_at", "approval_comment", "updated_at",
            ])
            return Response(AgentRunSerializer(run).data)

        pending = run.steps.filter(outcome="blocked_approval").order_by("-index", "-id").first()
        if pending is None or not pending.approval_token:
            return Response({"message": "No pending approval."}, status=409)

        _require(request, TOOL_PERMISSIONS.get(pending.tool_name or "", "campaigns.manage"))
        run.approved_by = request.user
        run.approved_at = now
        run.approval_comment = comment
        run.save(update_fields=["approved_by", "approved_at", "approval_comment", "updated_at"])
        try:
            resume_agent_run(run=run, approval_token=pending.approval_token)
        except PlannerConfigurationUnavailable as exc:
            return Response({
                "code": "planner_configuration_unavailable",
                "message": str(exc),
            }, status=409)
        except (KeyError, ValueError) as exc:
            return Response({"message": str(exc)}, status=409)
        run.refresh_from_db()
        return Response(AgentRunSerializer(run).data)


class AgentRunStartView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(
        tags=["Agent"],
        request=AgentRunStartSerializer,
        responses={200: AgentRunStartResultSerializer},
    )
    def post(self, request):
        agent_type = request.data.get("agent_type")
        if agent_type not in AGENT_PERMISSIONS:
            return Response({"message": f"Unknown agent type {agent_type!r}."}, status=400)
        _require(request, PermissionCode.AGENTS_RUN)
        _require(request, AGENT_PERMISSIONS[agent_type])
        organization = request.organization
        actor_id = str(request.user.id)
        mission_id = (
            str(request.data["mission_id"]) if request.data.get("mission_id") else None
        )
        social_ops_key = None
        if agent_type == "social_ops" and mission_id:
            social_ops_key = (
                f"social-ops:mission:{mission_id}:{request.data.get('content_id')}:"
                f"{request.data.get('account_id')}:"
                f"{request.data.get('scheduled_at') or 'immediate'}"
            )
        try:
            if agent_type == "content_strategy":
                result = run_content_strategy_agent(
                    organization=organization,
                    creator_id=actor_id,
                    mission_id=mission_id,
                )
            elif agent_type == "content_creation":
                result = run_content_creation_agent(
                    organization=organization,
                    brief_id=str(request.data["brief_id"]),
                    actor_id=actor_id,
                    values=request.data.get("values", {}),
                    product_id=str(request.data["product_id"]),
                    platform_id=str(request.data["platform_id"]),
                    asset_ids=request.data.get("asset_ids"),
                )
            elif agent_type == "platform_variants":
                result = run_platform_variants_agent(
                    organization=organization,
                    master_id=str(request.data["master_id"]),
                    actor_id=actor_id,
                )
            elif agent_type == "social_ops":
                result = run_social_ops_agent(
                    organization=organization,
                    content_id=str(request.data["content_id"]),
                    account_id=str(request.data["account_id"]),
                    scheduled_at=request.data.get("scheduled_at"),
                    timezone_name=request.data.get("timezone_name", "UTC"),
                    idempotency_key=social_ops_key,
                )
        except (KeyError, ValueError) as exc:
            return Response({"message": str(exc)}, status=400)

        if mission_id:
            mission = GrowthMission.objects.filter(
                organization=organization, id=mission_id
            ).first()
            run = None
            if agent_type == "content_strategy":
                run = AgentRun.objects.filter(
                    organization=organization,
                    idempotency_key=f"content-strategy:{organization.id}:{mission_id}",
                ).first()
            elif agent_type == "social_ops" and social_ops_key:
                run = AgentRun.objects.filter(
                    organization=organization,
                    idempotency_key=social_ops_key,
                ).first()
            if mission is not None and run is not None:
                lane = (
                    MissionEntityLink.Lane.OUTREACH
                    if agent_type == "proactive"
                    else MissionEntityLink.Lane.SOCIAL
                )
                link_mission_entity(
                    mission=mission, entity=run, lane=lane, actor=request.user
                )
                sync_mission_links_from_agent_run(run=run, actor=request.user)

        return Response({
            "status": result.status,
            "terminal_reason": result.terminal_reason,
            "pending_approval_token": (
                result.pending_approval.approval_token
                if result.pending_approval else None
            ),
        })


class GrowthEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthEvent
        fields = [
            "id",
            "event_type",
            "entity_type",
            "entity_id",
            "payload",
            "occurred_at",
            "published_at",
        ]


class GrowthEventAcknowledgeSerializer(serializers.Serializer):
    event_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)


class GrowthEventAcknowledgeResultSerializer(serializers.Serializer):
    acknowledged = serializers.IntegerField()


class GrowthEventListView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Gateway events"], responses={200: GrowthEventSerializer(many=True)})
    def get(self, request):
        events = GrowthEvent.objects.filter(organization=request.organization).order_by(
            "occurred_at", "id",
        )
        if request.query_params.get("unpublished") == "true":
            events = events.filter(published_at__isnull=True)
        return Response(GrowthEventSerializer(events[:200], many=True).data)


class GrowthEventAcknowledgeView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(
        tags=["Gateway events"],
        request=GrowthEventAcknowledgeSerializer,
        responses={200: GrowthEventAcknowledgeResultSerializer},
    )
    def post(self, request):
        serializer = GrowthEventAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = mark_events_published(
            organization=request.organization,
            event_ids=serializer.validated_data["event_ids"],
        )
        return Response({"acknowledged": count})
