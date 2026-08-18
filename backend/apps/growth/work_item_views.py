from dataclasses import asdict

from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanReadMissions

from .work_items import WorkItemProjection, project_work_items


_WORK_ITEM_PERMISSIONS = {"agents.approve", "campaigns.review", "publishing.manage"}


def _projection_payload(item: WorkItemProjection) -> dict:
    payload = asdict(item)
    payload["created_at"] = (
        item.created_at.isoformat() if item.created_at else None
    )
    return payload


class WorkItemListView(APIView):
    permission_classes = [CanReadMissions]

    @extend_schema(
        tags=["Growth missions"],
        responses={200: dict},
    )
    def get(self, request):
        permissions = request.membership.role.permissions
        if not (permissions and _WORK_ITEM_PERMISSIONS.intersection(permissions)):
            return Response(
                {"detail": "Insufficient permission to view work items."}, status=403
            )
        mission_id = request.query_params.get("mission")
        mission = None
        if mission_id:
            from .models import GrowthMission
            from django.shortcuts import get_object_or_404

            mission = get_object_or_404(
                GrowthMission, id=mission_id, organization=request.organization
            )
        items = project_work_items(organization=request.organization, mission=mission)
        limit = _positive_int(request.query_params.get("limit"), 100)
        offset = _positive_int(request.query_params.get("offset"), 0)
        page = items[offset:offset + limit]
        return Response([_projection_payload(item) for item in page])


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)
