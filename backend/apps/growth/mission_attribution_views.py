from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanReadMissions

from .mission_attribution import build_mission_attribution
from .models import GrowthMission


class MissionAttributionView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(tags=["Growth missions"], responses={200: dict})
    def get(self, request):
        mission_id = request.query_params.get("mission")
        mission = get_object_or_404(
            GrowthMission, id=mission_id, organization=request.organization
        )
        return Response(build_mission_attribution(mission=mission))
