"""HTTP endpoints for inspecting and approving agent runs."""

from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCampaigns, CanReadCampaigns

from .agent.resume import resume_agent_run
from .agent.content_creation_tools import (
    run_content_creation_agent,
    run_platform_variants_agent,
)
from .agent.content_tools import run_content_strategy_agent
from .agent.publishing_tools import run_social_ops_agent
from .growth_events import mark_events_published
from .models import AgentRun, AgentRunStep, GrowthEvent


class AgentRunStepSerializer(serializers.ModelSerializer):
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
        ]


class AgentRunSerializer(serializers.ModelSerializer):
    steps = AgentRunStepSerializer(many=True, read_only=True)
    pending_approval = serializers.SerializerMethodField()

    class Meta:
        model = AgentRun
        fields = [
            "id",
            "goal",
            "status",
            "terminal_reason",
            "created_at",
            "updated_at",
            "steps",
            "pending_approval",
        ]

    def get_pending_approval(self, obj: AgentRun) -> dict | None:
        step = obj.steps.filter(outcome="blocked_approval").order_by("-index", "-id").first()
        if step is None:
            return None
        return {
            "tool_name": step.tool_name,
            "tool_args": step.args,
            "reasoning": step.reasoning,
        }


class AgentRunListView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Agent"])
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

    @extend_schema(tags=["Agent"])
    def get(self, request, run_id):
        run = get_object_or_404(AgentRun, id=run_id, organization=request.organization)
        return Response(AgentRunSerializer(run).data)


class AgentRunApproveView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Agent"])
    def post(self, request, run_id):
        run = get_object_or_404(AgentRun, id=run_id, organization=request.organization)
        if run.status != AgentRun.Status.WAITING_APPROVAL:
            return Response({"message": "Run is not waiting for approval."}, status=409)

        decision = request.data.get("decision", "approve")
        if decision == "reject":
            run.status = AgentRun.Status.REJECTED
            run.terminal_reason = "Rejected by reviewer."
            run.save(update_fields=["status", "terminal_reason", "updated_at"])
            return Response(AgentRunSerializer(run).data)

        pending = run.steps.filter(outcome="blocked_approval").order_by("-index", "-id").first()
        if pending is None or not pending.approval_token:
            return Response({"message": "No pending approval."}, status=409)

        try:
            resume_agent_run(run=run, approval_token=pending.approval_token)
        except (KeyError, ValueError) as exc:
            return Response({"message": str(exc)}, status=409)
        run.refresh_from_db()
        return Response(AgentRunSerializer(run).data)


class AgentRunStartView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Agent"])
    def post(self, request):
        agent_type = request.data.get("agent_type")
        organization = request.organization
        actor_id = str(request.user.id)
        try:
            if agent_type == "content_strategy":
                result = run_content_strategy_agent(
                    organization=organization, creator_id=actor_id,
                )
            elif agent_type == "content_creation":
                result = run_content_creation_agent(
                    organization=organization,
                    brief_id=str(request.data["brief_id"]),
                    actor_id=actor_id,
                    values=request.data.get("values", {}),
                    product_id=str(request.data["product_id"]),
                    platform_id=str(request.data["platform_id"]),
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
                )
            else:
                return Response(
                    {"message": f"Unknown agent type {agent_type!r}."},
                    status=400,
                )
        except (KeyError, ValueError) as exc:
            return Response({"message": str(exc)}, status=400)

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


class GrowthEventListView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Gateway events"])
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
    )
    def post(self, request):
        serializer = GrowthEventAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = mark_events_published(
            organization=request.organization,
            event_ids=serializer.validated_data["event_ids"],
        )
        return Response({"acknowledged": count})
