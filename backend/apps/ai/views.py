from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanReadJobs

from .models import AIRun
from .serializers import (
    AIRunFilterSerializer,
    AIRunListSerializer,
    AIRunSerializer,
    AIRunValidationErrorSerializer,
)


class AIRunCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _validation(errors):
    return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


def _filters(request):
    names = {"job", "status", "cursor", "page_size"}
    errors = {
        name: ["Provide this filter at most once."]
        for name in names
        if len(request.query_params.getlist(name)) > 1
    }
    errors.update({
        name: ["Unknown field."]
        for name in sorted(set(request.query_params) - names)
    })
    if errors:
        return None, _validation(errors)
    serializer = AIRunFilterSerializer(data=request.query_params)
    if not serializer.is_valid():
        return None, _validation(serializer.errors)
    return serializer.validated_data, None


def _run(organization, run_id):
    try:
        return AIRun.objects.select_related("job", "prompt_version", "reviewed_by").get(
            pk=run_id, organization=organization,
        )
    except (AIRun.DoesNotExist, ValueError) as exc:
        raise Http404 from exc


class AIRunListView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(
        operation_id="ai_runs_list",
        parameters=[
            OpenApiParameter("job", OpenApiTypes.UUID),
            OpenApiParameter("status", OpenApiTypes.STR, enum=AIRun.Status.values),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            OpenApiParameter("page_size", OpenApiTypes.INT),
        ],
        responses={200: AIRunListSerializer, 400: AIRunValidationErrorSerializer},
    )
    def get(self, request):
        values, error = _filters(request)
        if error:
            return error
        queryset = AIRun.objects.filter(organization=request.organization).select_related(
            "job", "prompt_version", "reviewed_by",
        )
        if "job" in values:
            queryset = queryset.filter(job_id=values["job"])
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        paginator = AIRunCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(AIRunSerializer(page, many=True).data)


class AIRunDetailView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(operation_id="ai_runs_retrieve", responses={200: AIRunSerializer})
    def get(self, request, run_id):
        return Response(AIRunSerializer(_run(request.organization, run_id)).data)
