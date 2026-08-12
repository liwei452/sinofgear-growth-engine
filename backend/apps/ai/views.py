from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageCredentials, CanReadJobs

from .models import AIRun
from .serializers import (
    AIRunFilterSerializer,
    AIRunListSerializer,
    AIRunSerializer,
    AIRunValidationErrorSerializer,
    AIProviderConfigurationSerializer,
    AIProviderConfigurationTestResultSerializer,
    AIProviderConfigurationTestSerializer,
    AIProviderConfigurationWriteSerializer,
)
from .models import AIProviderConfiguration
from .provider_configuration import (
    ProviderConfigurationError,
    delete_deepseek_credential,
    test_and_save_deepseek_configuration,
    test_deepseek_configuration,
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


@extend_schema(tags=["AIRuns"])
class AIRunListView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(
        operation_id="ai_runs_list",
        parameters=[
            OpenApiParameter("job", OpenApiTypes.UUID),
            OpenApiParameter("status", OpenApiTypes.STR, enum=AIRun.Status.values),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
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


@extend_schema(tags=["AIRuns"])
class AIRunDetailView(APIView):
    permission_classes = [CanReadJobs]

    @extend_schema(operation_id="ai_runs_retrieve", responses={200: AIRunSerializer})
    def get(self, request, run_id):
        return Response(AIRunSerializer(_run(request.organization, run_id)).data)


class DuplicateSafeJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        import json

        raw = stream.read()
        charset = (parser_context or {}).get("encoding") or "utf-8"

        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ParseError("Duplicate JSON fields are not allowed.")
                result[key] = value
            return result

        parsed = None
        failed = False
        try:
            parsed = json.loads(raw.decode(charset), object_pairs_hook=unique_pairs)
        except (ParseError, UnicodeDecodeError, ValueError):
            failed = True
        if failed:
            raise ParseError("Malformed JSON.") from None
        return parsed


def _configuration_for(organization):
    try:
        return AIProviderConfiguration.objects.get(organization=organization)
    except AIProviderConfiguration.DoesNotExist:
        return AIProviderConfiguration(organization=organization)


@extend_schema(tags=["AIProviderConfiguration"])
class AIProviderConfigurationView(APIView):
    permission_classes = [CanManageCredentials]
    parser_classes = [DuplicateSafeJSONParser]

    @extend_schema(responses={200: AIProviderConfigurationSerializer})
    def get(self, request):
        return Response(AIProviderConfigurationSerializer(_configuration_for(request.organization)).data)

    @extend_schema(
        request=AIProviderConfigurationWriteSerializer,
        responses={
            200: AIProviderConfigurationSerializer,
            400: AIProviderConfigurationTestResultSerializer,
        },
    )
    def put(self, request):
        serializer = AIProviderConfigurationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        api_key = values.pop("api_key")
        try:
            configuration = test_and_save_deepseek_configuration(
                organization=request.organization,
                actor=request.user,
                api_key=api_key,
                limits=values,
            )
        except ProviderConfigurationError as error:
            return Response(
                {"connection_state": "FAILED", "recovery_code": error.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(AIProviderConfigurationSerializer(configuration).data)

    @extend_schema(responses={
        200: AIProviderConfigurationSerializer,
        400: AIProviderConfigurationTestResultSerializer,
    })
    def delete(self, request):
        try:
            configuration = delete_deepseek_credential(
                organization=request.organization, actor=request.user
            )
        except ProviderConfigurationError as error:
            return Response(
                {"connection_state": "FAILED", "recovery_code": error.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(AIProviderConfigurationSerializer(configuration).data)


@extend_schema(tags=["AIProviderConfiguration"])
class AIProviderConfigurationTestView(APIView):
    permission_classes = [CanManageCredentials]
    parser_classes = [DuplicateSafeJSONParser]

    @extend_schema(
        request=AIProviderConfigurationTestSerializer,
        responses={
            200: AIProviderConfigurationTestResultSerializer,
            400: AIProviderConfigurationTestResultSerializer,
        },
    )
    def post(self, request):
        serializer = AIProviderConfigurationTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            test_deepseek_configuration(
                organization=request.organization,
                api_key=serializer.validated_data.get("api_key"),
            )
        except ProviderConfigurationError as error:
            return Response(
                {"connection_state": "FAILED", "recovery_code": error.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"connection_state": "CONNECTED", "recovery_code": None})
