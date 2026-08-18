from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import (
    CanManageMissions,
    CanReadMissions,
    CanReviewMissions,
    CanRunAgents,
)

from .agent.acquisition import run_proactive_acquisition
from .agent.content_tools import run_content_strategy_agent
from .agent_views import AgentRunSerializer
from .mission_planning import (
    MissionPlanGenerationError,
    approve_mission_plan,
    generate_mission_plan,
)
from .mission_timeline import project_mission_timeline
from .mission_serializers import (
    GrowthMissionInputSerializer,
    GrowthMissionSerializer,
    MissionApprovePlanSerializer,
    MissionPlanSerializer,
    MissionStatusSerializer,
)
from .mission_services import (
    create_mission,
    link_mission_entity,
    mission_available_actions,
    sync_mission_links_from_agent_run,
    transition_mission,
    update_draft_mission,
)
from .models import (
    AgentRun,
    DiscoveryCandidate,
    GrowthMission,
    MissionEntityLink,
    MissionPlan,
)


def _available_actions(request, mission):
    permissions = request.membership.role.permissions
    return mission_available_actions(
        mission,
        can_manage="missions.manage" in permissions,
        can_review="missions.review" in permissions,
    )


def _serialize(request, mission):
    return GrowthMissionSerializer(
        mission, context={"available_actions": _available_actions(request, mission)}
    ).data


class MissionListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [CanManageMissions()]
        return [CanReadMissions()]

    @extend_schema(
        tags=["Growth missions"],
        responses={200: GrowthMissionSerializer(many=True)},
    )
    def get(self, request):
        missions = GrowthMission.objects.filter(organization=request.organization)
        return Response([_serialize(request, mission) for mission in missions])

    @extend_schema(
        tags=["Growth missions"],
        request=GrowthMissionInputSerializer,
        responses={201: GrowthMissionSerializer},
    )
    def post(self, request):
        serializer = GrowthMissionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mission = create_mission(
                organization=request.organization,
                actor=request.user,
                values=serializer.validated_data,
            )
        except ValidationError as exc:
            return Response({"detail": exc.message_dict}, status=400)
        return Response(_serialize(request, mission), status=201)


class MissionDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [CanManageMissions()]
        return [CanReadMissions()]

    @extend_schema(tags=["Growth missions"], responses={200: GrowthMissionSerializer})
    def get(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        return Response(_serialize(request, mission))

    @extend_schema(
        tags=["Growth missions"],
        request=GrowthMissionInputSerializer,
        responses={200: GrowthMissionSerializer},
    )
    def patch(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        serializer = GrowthMissionInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            mission = update_draft_mission(
                mission=mission,
                actor=request.user,
                values=serializer.validated_data,
            )
        except ValidationError as exc:
            return Response({"detail": exc.message_dict}, status=400)
        return Response(_serialize(request, mission))


class MissionGeneratePlanView(APIView):
    permission_classes = [CanManageMissions]

    @extend_schema(
        tags=["Growth missions"],
        request=None,
        responses={201: MissionPlanSerializer},
    )
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        try:
            plan = generate_mission_plan(mission=mission, actor=request.user)
        except MissionPlanGenerationError as exc:
            return Response({"detail": str(exc)}, status=422)
        return Response(MissionPlanSerializer(plan).data, status=201)


class MissionApprovePlanView(APIView):
    permission_classes = [CanReviewMissions]

    @extend_schema(
        tags=["Growth missions"],
        request=MissionApprovePlanSerializer,
        responses={200: MissionPlanSerializer},
    )
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        serializer = MissionApprovePlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = get_object_or_404(
            MissionPlan,
            id=serializer.validated_data["plan_id"],
            organization=request.organization,
            mission=mission,
        )
        try:
            plan = approve_mission_plan(mission=mission, plan=plan, actor=request.user)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict}, status=400)
        return Response(MissionPlanSerializer(plan).data)


class MissionStatusView(APIView):
    permission_classes = [CanManageMissions]

    @extend_schema(
        tags=["Growth missions"],
        request=MissionStatusSerializer,
        responses={200: GrowthMissionSerializer},
    )
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        serializer = MissionStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            mission = transition_mission(
                mission=mission,
                actor=request.user,
                target_status=serializer.validated_data["status"],
                reason=serializer.validated_data.get("reason", ""),
            )
        except ValidationError as exc:
            return Response({"detail": exc.message_dict}, status=400)
        return Response(_serialize(request, mission))


class MissionTimelineView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def get(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        items = project_mission_timeline(mission=mission)
        return Response(
            [
                {
                    "occurred_at": item.occurred_at.isoformat(),
                    "lane": item.lane,
                    "state": item.state,
                    "title": item.title,
                    "summary": item.summary,
                    "evidence_type": item.evidence_type,
                    "evidence_id": item.evidence_id,
                }
                for item in items
            ]
        )


class MissionStartOutreachView(APIView):
    permission_classes = [CanRunAgents]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def post(self, request, mission_id, candidate_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        candidate = get_object_or_404(
            DiscoveryCandidate,
            id=candidate_id,
            organization=request.organization,
            status=DiscoveryCandidate.Status.ACCEPTED,
        )
        run_proactive_acquisition(
            organization=request.organization, candidate_id=str(candidate.id)
        )
        run = get_object_or_404(
            AgentRun,
            organization=request.organization,
            idempotency_key=f"proactive:{candidate.id}",
        )
        link_mission_entity(
            mission=mission,
            entity=run,
            lane=MissionEntityLink.Lane.OUTREACH,
            actor=request.user,
        )
        sync_mission_links_from_agent_run(run=run, actor=request.user)
        return Response(AgentRunSerializer(run).data)


class MissionStartContentStrategyView(APIView):
    permission_classes = [CanRunAgents]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        run_content_strategy_agent(
            organization=request.organization,
            creator_id=str(request.user.id),
            mission_id=str(mission.id),
        )
        run = get_object_or_404(
            AgentRun,
            organization=request.organization,
            idempotency_key=f"content-strategy:{request.organization.id}:{mission.id}",
        )
        link_mission_entity(
            mission=mission,
            entity=run,
            lane=MissionEntityLink.Lane.SOCIAL,
            actor=request.user,
        )
        sync_mission_links_from_agent_run(run=run, actor=request.user)
        return Response(AgentRunSerializer(run).data)
