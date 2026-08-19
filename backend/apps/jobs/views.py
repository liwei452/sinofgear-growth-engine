from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageJobs, CanReadJobs

from .models import Job
from .serializers import (
    JobConflictSerializer,
    EmptyActionSerializer,
    JobErrorSerializer,
    JobFilterSerializer,
    JobListSerializer,
    JobSerializer,
    JobValidationErrorSerializer,
)
from .services import JobConflictError, JobService


class JobCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _validation(errors):
    return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


def _validate_filters(request):
    names = {"type", "status", "job_id", "cursor", "page_size"}
    unknown = set(request.query_params) - names
    repeated = {
        name: ["Provide this filter at most once."]
        for name in names
        if len(request.query_params.getlist(name)) > 1
    }
    if unknown:
        repeated.update({name: ["Unknown field."] for name in sorted(unknown)})
    if repeated:
        return None, _validation(repeated)
    serializer = JobFilterSerializer(data=request.query_params)
    if not serializer.is_valid():
        return None, _validation(serializer.errors)
    return serializer.validated_data, None


def _job(organization, job_id):
    try:
        return Job.objects.prefetch_related("ai_runs").get(
            pk=job_id, organization=organization,
        )
    except (Job.DoesNotExist, ValueError) as exc:
        raise Http404 from exc


@extend_schema(tags=["Jobs"])
class JobListView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(
        operation_id="jobs_list",
        parameters=[
            OpenApiParameter("type", OpenApiTypes.STR, enum=Job.Type.values),
            OpenApiParameter("status", OpenApiTypes.STR, enum=Job.Status.values),
            OpenApiParameter("job_id", OpenApiTypes.UUID),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
        ],
        responses={
            200: JobListSerializer,
            400: JobValidationErrorSerializer,
            403: JobErrorSerializer,
        },
    )
    def get(self, request):
        values, error = _validate_filters(request)
        if error:
            return error
        queryset = Job.objects.filter(
            organization=request.organization,
        ).prefetch_related("ai_runs")
        for field in ("type", "status"):
            if field in values:
                queryset = queryset.filter(**{field: values[field]})
        if "job_id" in values:
            queryset = queryset.filter(pk=values["job_id"])
        paginator = JobCursorPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(JobSerializer(page, many=True).data)


@extend_schema(tags=["Jobs"])
class JobDetailView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(
        operation_id="jobs_retrieve",
        responses={200: JobSerializer, 403: JobErrorSerializer, 404: JobErrorSerializer},
    )
    def get(self, request, job_id):
        return Response(JobSerializer(_job(request.organization, job_id)).data)


@extend_schema(tags=["Jobs"])
class JobActionView(APIView):
    permission_classes = [CanManageJobs]
    action = ""

    @extend_schema(
        request=EmptyActionSerializer,
        responses={
            200: JobSerializer,
            400: JobValidationErrorSerializer,
            403: JobErrorSerializer,
            404: JobErrorSerializer,
            409: JobConflictSerializer,
        },
    )
    def post(self, request, job_id):
        serializer = EmptyActionSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        job = _job(request.organization, job_id)
        try:
            if self.action == "retry":
                job = JobService.retry(job.id, organization=request.organization)
                self._dispatch_retry(job)
            else:
                job = JobService.cancel(job.id, organization=request.organization)
        except JobConflictError as exc:
            return Response(
                {"code": "invalid_job_transition", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(JobSerializer(job).data)

    @staticmethod
    def _dispatch_retry(job):
        if job.type == Job.Type.CONTENT_PLATFORM_VARIANTS:
            from apps.content.tasks import generate_platform_variants_job

            generate_platform_variants_job.delay(str(job.id))


class JobRetryView(JobActionView):
    action = "retry"


class JobCancelView(JobActionView):
    action = "cancel"
