from django.db import transaction
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageCredentials, CanReadJobs, CanReadMemberships
from integrations.ai.providers import DeepSeekAIProvider
from integrations.secrets import decrypt_secret, encrypt_secret

from .models import AIRun, OrganizationAIProviderConfig
from .provider_config import provider_config_payload
from .serializers import (
    AIRunFilterSerializer,
    AIRunListSerializer,
    AIRunSerializer,
    AIRunValidationErrorSerializer,
    AIProviderConfigSerializer,
    AIProviderConfigWriteSerializer,
    AIProviderConnectionTestSerializer,
    ProductAIStatusSerializer,
)
from .runtime import product_ai_status


@extend_schema(tags=["AIRuns"])
class ProductAIStatusView(APIView):
    permission_classes = [CanReadMemberships]

    @extend_schema(responses={200: ProductAIStatusSerializer})
    def get(self, request):
        return Response(product_ai_status(request.organization))


@extend_schema(tags=["AIProviderConfig"])
class AIProviderConfigView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(responses={200: AIProviderConfigSerializer})
    def get(self, request):
        config = OrganizationAIProviderConfig.objects.filter(
            organization=request.organization
        ).first()
        return Response(provider_config_payload(config))

    @extend_schema(
        request=AIProviderConfigWriteSerializer,
        responses={200: AIProviderConfigSerializer},
    )
    @transaction.atomic
    def put(self, request):
        serializer = AIProviderConfigWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        values = dict(serializer.validated_data)
        api_key = values.pop("api_key", None)
        config, _created = OrganizationAIProviderConfig.objects.select_for_update().get_or_create(
            organization=request.organization
        )
        if values["enabled"] and not (api_key or config.encrypted_api_key):
            return _validation({"api_key": ["启用真实模型前必须配置 API Key。"]})
        for field, value in values.items():
            setattr(config, field, value)
        update_fields = [*values]
        if api_key:
            config.encrypted_api_key = encrypt_secret(api_key)
            update_fields.append("encrypted_api_key")
        config.save(update_fields=[*update_fields, "updated_at"])
        return Response(provider_config_payload(config))

    @extend_schema(responses={204: None})
    @transaction.atomic
    def delete(self, request):
        config = OrganizationAIProviderConfig.objects.select_for_update().filter(
            organization=request.organization
        ).first()
        if config:
            config.encrypted_api_key = ""
            config.enabled = False
            config.daily_reserved_micros = 0
            config.save(update_fields=[
                "encrypted_api_key", "enabled", "daily_reserved_micros", "updated_at",
            ])
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["AIProviderConfig"])
class AIProviderConfigTestView(APIView):
    permission_classes = [CanManageCredentials]

    @extend_schema(
        request=None,
        responses={200: AIProviderConnectionTestSerializer, 400: AIProviderConnectionTestSerializer},
    )
    def post(self, request):
        config = OrganizationAIProviderConfig.objects.filter(
            organization=request.organization
        ).first()
        if not config or not config.encrypted_api_key:
            return Response(
                {"ok": False, "error_code": "configuration_required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tested_at = timezone.now()
        try:
            api_key = decrypt_secret(config.encrypted_api_key)
            result = DeepSeekAIProvider(
                api_key=api_key,
                model=config.model,
                max_attempts=1,
            ).test_connection()
        except Exception:
            OrganizationAIProviderConfig.objects.filter(pk=config.pk).update(
                last_tested_at=tested_at,
                last_error_code="connection_failed",
            )
            return Response(
                {"ok": False, "error_code": "connection_failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        OrganizationAIProviderConfig.objects.filter(pk=config.pk).update(
            last_tested_at=tested_at,
            last_success_at=tested_at,
            last_error_code="",
        )
        return Response(result)


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
