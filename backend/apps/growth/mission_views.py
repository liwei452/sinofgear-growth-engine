from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.content.models import PlatformContent
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
    ChannelPackage,
    DiscoveryCandidate,
    GrowthMission,
    GrowthPublishBatch,
    MissionEntityLink,
    MissionPlan,
    TargetAccount,
)
from .publishing import (
    PublishBatchConflict,
    PublishPackageSelectionInvalid,
    create_publish_batch,
)
from .serializers import GrowthPublishBatchSerializer
from .services import approve_channel_package


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
        if mission.status != GrowthMission.Status.RUNNING:
            return Response(
                {"detail": "Only running missions can start outreach."}, status=409
            )
        candidate = get_object_or_404(
            DiscoveryCandidate,
            id=candidate_id,
            organization=request.organization,
            status=DiscoveryCandidate.Status.ACCEPTED,
        )
        link_mission_entity(
            mission=mission,
            entity=candidate,
            lane=MissionEntityLink.Lane.ACQUISITION,
            actor=request.user,
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


class MissionCandidatesView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def get(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        candidate_ids = MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=MissionEntityLink.EntityType.DISCOVERY_CANDIDATE,
        ).values_list("entity_id", flat=True)
        candidates = DiscoveryCandidate.objects.filter(
            organization=request.organization,
            id__in=candidate_ids,
            status=DiscoveryCandidate.Status.ACCEPTED,
        ).order_by("-score", "company_name")
        return Response([
            {"id": str(candidate.id), "company_name": candidate.company_name}
            for candidate in candidates
        ])


class MissionOutreachSummaryView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def get(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        candidate_ids = MissionEntityLink.objects.filter(
            mission=mission,
            entity_type=MissionEntityLink.EntityType.DISCOVERY_CANDIDATE,
        ).values_list("entity_id", flat=True)
        candidates = DiscoveryCandidate.objects.filter(
            organization=request.organization,
            id__in=candidate_ids,
            status=DiscoveryCandidate.Status.ACCEPTED,
        ).order_by("-score", "company_name")

        items = []
        for candidate in candidates:
            account = TargetAccount.objects.filter(
                organization=request.organization,
                source_identity=f"candidate:{candidate.id}",
            ).first()
            draft = None
            follow_up_stage = None
            latest_message = None
            run = AgentRun.objects.filter(
                organization=request.organization,
                idempotency_key=f"proactive:{candidate.id}",
            ).first()

            if account is not None:
                draft_record = account.outreach_drafts.order_by("-created_at", "-id").first()
                if draft_record is not None:
                    draft = {
                        "id": str(draft_record.id),
                        "english_draft": draft_record.english_draft,
                        "chinese_explanation": draft_record.chinese_explanation,
                        "status": draft_record.status,
                    }
                follow_up = account.follow_ups.first()
                if follow_up is not None:
                    follow_up_stage = follow_up.stage
                message = account.outreach_messages.order_by("-created_at", "-id").first()
                if message is not None:
                    latest_message = {
                        "id": str(message.id),
                        "status": message.status,
                        "provider": message.provider,
                        "sent_at": message.sent_at.isoformat() if message.sent_at else None,
                    }

            pending = None
            if run is not None:
                pending_step = run.steps.filter(outcome="blocked_approval").order_by(
                    "-index", "-id",
                ).first()
                if pending_step is not None:
                    pending = pending_step.tool_name

            items.append({
                "candidate_id": str(candidate.id),
                "company_name": candidate.company_name,
                "account_id": str(account.id) if account else None,
                "follow_up_stage": follow_up_stage,
                "draft": draft,
                "latest_message": latest_message,
                "agent_run": {
                    "id": str(run.id),
                    "status": run.status,
                    "pending_tool": pending,
                } if run is not None else None,
            })
        return Response(items)


class MissionContentSummaryView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def get(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        platform_ids = set(
            MissionEntityLink.objects.filter(
                mission=mission,
                entity_type=MissionEntityLink.EntityType.PLATFORM_CONTENT,
            ).values_list("entity_id", flat=True)
        )
        package_ids = set(
            MissionEntityLink.objects.filter(
                mission=mission,
                entity_type=MissionEntityLink.EntityType.CHANNEL_PACKAGE,
            ).values_list("entity_id", flat=True)
        )
        batch_ids = set(
            MissionEntityLink.objects.filter(
                mission=mission,
                entity_type=MissionEntityLink.EntityType.PUBLISH_BATCH,
            ).values_list("entity_id", flat=True)
        )
        platforms = PlatformContent.objects.filter(
            organization=request.organization, id__in=platform_ids
        ).select_related("platform")
        packages = ChannelPackage.objects.filter(
            organization=request.organization, id__in=package_ids
        )
        batches = GrowthPublishBatch.objects.filter(
            organization=request.organization, id__in=batch_ids
        ).order_by("-created_at", "-id")[:5]
        return Response({
            "platform_contents": [
                {
                    "id": str(c.id),
                    "platform_code": c.platform.code,
                    "status": c.status,
                    "title": (c.payload or {}).get("title", ""),
                }
                for c in platforms
            ],
            "channel_packages": [
                {"id": str(p.id), "channel": p.channel, "status": p.status}
                for p in packages
            ],
            "publish_batches": GrowthPublishBatchSerializer(batches, many=True).data,
        })


class MissionPublishView(APIView):
    permission_classes = [CanManageMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        if mission.status != GrowthMission.Status.RUNNING:
            return Response(
                {"detail": "Only running missions can publish."}, status=409
            )
        package_ids = list(
            MissionEntityLink.objects.filter(
                mission=mission,
                entity_type=MissionEntityLink.EntityType.CHANNEL_PACKAGE,
            ).values_list("entity_id", flat=True)
        )
        packages = list(
            ChannelPackage.objects.filter(
                organization=request.organization, id__in=package_ids
            ).order_by("channel", "id")
        )
        if not packages:
            return Response(
                {
                    "code": "NO_CHANNEL_PACKAGES",
                    "message": "还没有可发布的渠道内容包。",
                },
                status=409,
            )
        for package in packages:
            approve_channel_package(package=package)
        key = request.headers.get("Idempotency-Key", "").strip() or f"mission-publish:{mission.id}"
        try:
            batch = create_publish_batch(
                organization=request.organization,
                actor=request.user,
                package_ids=[str(package.id) for package in packages],
                idempotency_key=key,
            )
        except (PublishBatchConflict, PublishPackageSelectionInvalid) as error:
            return Response({"code": "PUBLISH_FAILED", "message": str(error)}, status=409)
        link_mission_entity(
            mission=mission,
            entity=batch,
            lane=MissionEntityLink.Lane.SOCIAL,
            actor=request.user,
        )
        return Response(GrowthPublishBatchSerializer(batch).data)


class MissionStartContentStrategyView(APIView):
    permission_classes = [CanRunAgents]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def post(self, request, mission_id):
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        if mission.status != GrowthMission.Status.RUNNING:
            return Response(
                {"detail": "Only running missions can start content strategy."}, status=409
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
