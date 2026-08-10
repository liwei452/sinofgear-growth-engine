from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.openapi import bounded_integer_query_parameter
from apps.common.renderers import recoverable_error
from apps.identity.permissions import CanManageSources, CanReadSources

from .models import (
    IngestionBatch,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
)
from .serializers import (
    IngestionAcceptedSerializer,
    IngestionBatchCreateSerializer,
    IngestionBatchListSerializer,
    IngestionBatchSerializer,
    MonitoringTargetCreateSerializer,
    MonitoringTargetListSerializer,
    MonitoringTargetSerializer,
    PageQuerySerializer,
    SourceContentListSerializer,
    SourceContentSerializer,
    SourceErrorSerializer,
    SourceEvidenceListSerializer,
    SourceEvidenceSerializer,
    SourceMutationErrorSerializer,
    SourceSignalListSerializer,
    SourceSignalSerializer,
    SourceValidationErrorSerializer,
)
from .services import SourceIdempotencyConflictError


PAGE_PARAMETERS = [
    OpenApiParameter("cursor", OpenApiTypes.STR),
    bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
]
ERROR_RESPONSES = {403: SourceErrorSerializer, 404: SourceErrorSerializer}


def _error_values(value):
    if isinstance(value, dict):
        return {key: _error_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_error_values(item) for item in value]
    return str(value)


def _validation_response(error, *, recoverable=False):
    if isinstance(error, DjangoValidationError):
        values = (
            error.message_dict
            if hasattr(error, "message_dict")
            else {"non_field_errors": error.messages}
        )
    else:
        values = error
    data = {"errors": _error_values(values)}
    if recoverable:
        data = recoverable_error(data, status.HTTP_400_BAD_REQUEST)
    return Response(data, status=status.HTTP_400_BAD_REQUEST)


def _page_values(request):
    serializer = PageQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        return None, _validation_response(serializer.errors, recoverable=True)
    return serializer.validated_data, None


class SourceCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


class OrganizationListView(APIView):
    permission_classes = [CanReadSources]
    model = None
    serializer_class = None

    def queryset(self, request):
        return self.model.objects.filter(organization=request.organization)

    def list(self, request):
        _values, error = _page_values(request)
        if error:
            return error
        paginator = SourceCursorPagination()
        try:
            page = paginator.paginate_queryset(self.queryset(request), request, view=self)
        except NotFound:
            return _validation_response(
                {"cursor": ["Invalid or expired cursor."]}, recoverable=True
            )
        return paginator.get_paginated_response(
            self.serializer_class(page, many=True).data
        )


@extend_schema(tags=["Sources"])
class MonitoringTargetListView(OrganizationListView):
    model = MonitoringTarget
    serializer_class = MonitoringTargetSerializer

    def get_permissions(self):
        permission = CanReadSources if self.request.method == "GET" else CanManageSources
        return [permission()]

    @extend_schema(
        operation_id="monitoring_targets_list",
        parameters=PAGE_PARAMETERS,
        responses={
            200: MonitoringTargetListSerializer,
            400: SourceValidationErrorSerializer,
            403: SourceErrorSerializer,
        },
    )
    def get(self, request):
        return self.list(request)

    @extend_schema(
        operation_id="monitoring_targets_create",
        request=MonitoringTargetCreateSerializer,
        responses={
            201: MonitoringTargetSerializer,
            400: SourceMutationErrorSerializer,
            403: SourceMutationErrorSerializer,
        },
    )
    def post(self, request):
        serializer = MonitoringTargetCreateSerializer(
            data=request.data,
            context={"organization": request.organization, "creator": request.user},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            target = serializer.save()
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(
            MonitoringTargetSerializer(target).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Sources"])
class IngestionBatchListView(OrganizationListView):
    model = IngestionBatch
    serializer_class = IngestionBatchSerializer

    def get_permissions(self):
        permission = CanReadSources if self.request.method == "GET" else CanManageSources
        return [permission()]

    @extend_schema(
        operation_id="ingestion_batches_list",
        parameters=PAGE_PARAMETERS,
        responses={
            200: IngestionBatchListSerializer,
            400: SourceValidationErrorSerializer,
            403: SourceErrorSerializer,
        },
    )
    def get(self, request):
        return self.list(request)

    @extend_schema(
        operation_id="ingestion_batches_create",
        request=IngestionBatchCreateSerializer,
        responses={
            202: IngestionAcceptedSerializer,
            400: SourceMutationErrorSerializer,
            403: SourceMutationErrorSerializer,
            409: SourceMutationErrorSerializer,
        },
    )
    def post(self, request):
        serializer = IngestionBatchCreateSerializer(
            data=request.data,
            context={"organization": request.organization, "creator": request.user},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            batch, job = serializer.save()
        except SourceIdempotencyConflictError as error:
            return Response(
                {"code": "idempotency_conflict", "detail": str(error)},
                status=status.HTTP_409_CONFLICT,
            )
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(
            {
                "job_id": job.id,
                "ingestion_batch_id": batch.id,
                "status": batch.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(tags=["Sources"])
class SourceContentListView(OrganizationListView):
    model = SourceContent
    serializer_class = SourceContentSerializer

    @extend_schema(
        operation_id="source_contents_list",
        parameters=PAGE_PARAMETERS,
        responses={200: SourceContentListSerializer, 400: SourceValidationErrorSerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        return self.list(request)


@extend_schema(tags=["Sources"])
class SourceSignalListView(OrganizationListView):
    model = SourceSignal
    serializer_class = SourceSignalSerializer

    @extend_schema(
        operation_id="source_signals_list",
        parameters=PAGE_PARAMETERS,
        responses={200: SourceSignalListSerializer, 400: SourceValidationErrorSerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        return self.list(request)


@extend_schema(tags=["Sources"])
class SourceEvidenceListView(OrganizationListView):
    model = SourceEvidence
    serializer_class = SourceEvidenceSerializer

    @extend_schema(
        operation_id="source_evidences_list",
        parameters=PAGE_PARAMETERS,
        responses={200: SourceEvidenceListSerializer, 400: SourceValidationErrorSerializer, **ERROR_RESPONSES},
    )
    def get(self, request):
        return self.list(request)


@extend_schema(tags=["Sources"])
class SourceEvidenceDetailView(APIView):
    permission_classes = [CanReadSources]

    @extend_schema(
        operation_id="source_evidences_retrieve",
        responses={200: SourceEvidenceSerializer, **ERROR_RESPONSES},
    )
    def get(self, request, evidence_id):
        try:
            evidence = SourceEvidence.objects.get(
                pk=evidence_id, organization=request.organization
            )
        except SourceEvidence.DoesNotExist as error:
            raise Http404 from error
        return Response(SourceEvidenceSerializer(evidence).data)
