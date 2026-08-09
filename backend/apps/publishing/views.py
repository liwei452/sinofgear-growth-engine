from collections import defaultdict
from zoneinfo import ZoneInfo

from django.db.models import Exists, OuterRef, Prefetch
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.campaigns.models import ContentBriefPlatform
from apps.content.models import PlatformContent
from apps.identity.permissions import CanManagePublishing, CanReadPublishing
from apps.platforms.models import SocialAccount

from .models import PublishAttempt, PublishTask
from .serializers import (
    CalendarFilterSerializer, EmptyActionSerializer, PublishCreateSerializer,
    PublishFilterSerializer, PublishingErrorSerializer, PublishTaskSerializer,
)
from .services import (
    PublishingConflict, cancel_publish_task, create_publish_task,
    publish_task_is_consistent, retry_publish_task, validate_idempotency_key,
)


class PublishPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _safe_queryset(organization):
    return (
        PublishTask.objects.filter(organization=organization)
        .select_related(
            "platform_content__platform",
            "platform_content__master_content__brief",
            "platform_content__master_content__generation_job",
            "platform_content__master_content__ai_run",
            "platform_content__master_content__previous_version",
            "platform_content__previous_version",
            "social_account__platform", "social_account__credential", "platform",
            "published_post__attempt",
        )
        .prefetch_related(
            Prefetch("attempts", queryset=PublishAttempt.objects.order_by("number"), to_attr="_safe_attempts")
        )
        .annotate(
            _selected_platform=Exists(
                ContentBriefPlatform.objects.filter(
                    brief_id=OuterRef("platform_content__master_content__brief_id"),
                    platform_id=OuterRef("platform_id"),
                )
            )
        )
    )


def _task(organization, task_id):
    try:
        task = _safe_queryset(organization).get(pk=task_id)
    except (PublishTask.DoesNotExist, ValueError) as exc:
        raise Http404 from exc
    if not publish_task_is_consistent(task):
        raise Http404
    return task


def _validation(errors):
    return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


def _conflict(exc):
    return Response(
        {
            "code": "publishing_conflict", "message": str(exc),
            "recovery_action": "Refresh the task or reconnect the account, then retry.",
        },
        status=status.HTTP_409_CONFLICT,
    )


def _validated_query(request, serializer_class):
    repeated = {
        name: ["Provide this filter at most once."]
        for name in request.query_params
        if len(request.query_params.getlist(name)) > 1
    }
    serializer = serializer_class(data=request.query_params)
    if repeated or not serializer.is_valid():
        return None, _validation({**serializer.errors, **repeated})
    return serializer.validated_data, None


class PublishTaskListView(APIView):
    serializer_class = PublishTaskSerializer

    def get_permissions(self):
        classes = [CanManagePublishing] if self.request.method == "POST" else [CanReadPublishing]
        return [permission() for permission in classes]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=PublishTask.Status.values),
            OpenApiParameter("platform", OpenApiTypes.UUID),
            OpenApiParameter("account", OpenApiTypes.UUID),
            OpenApiParameter("content", OpenApiTypes.UUID),
        ],
        responses={200: PublishTaskSerializer(many=True)},
    )
    def get(self, request):
        values, error = _validated_query(request, PublishFilterSerializer)
        if error:
            return error
        queryset = _safe_queryset(request.organization)
        mapping = {
            "status": "status", "platform": "platform_id",
            "account": "social_account_id", "content": "platform_content_id",
        }
        for name, field in mapping.items():
            if name in values:
                queryset = queryset.filter(**{field: values[name]})
        paginator = PublishPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        safe = [task for task in page if publish_task_is_consistent(task)]
        return paginator.get_paginated_response(PublishTaskSerializer(safe, many=True).data)

    @extend_schema(
        request=PublishCreateSerializer,
        parameters=[
            OpenApiParameter(
                "Idempotency-Key", OpenApiTypes.STR, location=OpenApiParameter.HEADER,
                required=True, description="Organization-scoped idempotency key (1-128 visible ASCII characters).",
            )
        ],
        responses={201: PublishTaskSerializer, 409: PublishingErrorSerializer},
    )
    def post(self, request):
        serializer = PublishCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        key = request.headers.get("Idempotency-Key")
        if key is None:
            return _validation({"Idempotency-Key": ["This header is required."]})
        try:
            key = validate_idempotency_key(key)
        except PublishingConflict as exc:
            return _validation({"Idempotency-Key": [str(exc)]})
        values = serializer.validated_data
        try:
            content = PlatformContent.objects.get(
                pk=values["platform_content_id"], organization=request.organization
            )
            account = SocialAccount.objects.get(
                pk=values["social_account_id"], organization=request.organization
            )
        except (PlatformContent.DoesNotExist, SocialAccount.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        try:
            task = create_publish_task(
                content=content, account=account, idempotency_key=key,
                scheduled_at=values.get("scheduled_at"),
                timezone_name=values["timezone"], actor=request.user,
            )
        except PublishingConflict as exc:
            return _conflict(exc)
        return Response(PublishTaskSerializer(_task(request.organization, task.id)).data, status=201)


class PublishScheduleView(PublishTaskListView):
    @extend_schema(
        request=PublishCreateSerializer,
        parameters=[OpenApiParameter(
            "Idempotency-Key", OpenApiTypes.STR, location=OpenApiParameter.HEADER, required=True,
        )],
        responses={201: PublishTaskSerializer, 409: PublishingErrorSerializer},
    )
    def post(self, request):
        return super().post(request)


class PublishTaskDetailView(APIView):
    permission_classes = [CanReadPublishing]
    serializer_class = PublishTaskSerializer

    def get(self, request, task_id):
        return Response(PublishTaskSerializer(_task(request.organization, task_id)).data)


class PublishActionView(APIView):
    permission_classes = [CanManagePublishing]
    serializer_class = EmptyActionSerializer
    action = ""

    @extend_schema(
        request=EmptyActionSerializer,
        responses={200: PublishTaskSerializer, 409: PublishingErrorSerializer},
    )
    def post(self, request, task_id):
        serializer = EmptyActionSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        task = _task(request.organization, task_id)
        try:
            if self.action == "retry":
                task = retry_publish_task(task, actor=request.user)
            else:
                task = cancel_publish_task(task, actor=request.user)
        except PublishingConflict as exc:
            return _conflict(exc)
        return Response(PublishTaskSerializer(_task(request.organization, task.id)).data)


class PublishCancelView(PublishActionView):
    action = "cancel"


class PublishRetryView(PublishActionView):
    action = "retry"


class PublishCalendarView(APIView):
    permission_classes = [CanReadPublishing]
    serializer_class = CalendarFilterSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("start", OpenApiTypes.DATETIME, required=True),
            OpenApiParameter("end", OpenApiTypes.DATETIME, required=True),
            OpenApiParameter("timezone", OpenApiTypes.STR, required=True, description="IANA timezone used only for local-date grouping."),
            OpenApiParameter("platform", OpenApiTypes.UUID),
            OpenApiParameter("account", OpenApiTypes.UUID),
            OpenApiParameter("product", OpenApiTypes.UUID),
            OpenApiParameter("campaign", OpenApiTypes.UUID),
            OpenApiParameter("country", OpenApiTypes.STR),
            OpenApiParameter("status", OpenApiTypes.STR, enum=PublishTask.Status.values),
        ],
    )
    def get(self, request):
        values, error = _validated_query(request, CalendarFilterSerializer)
        if error:
            return error
        queryset = _safe_queryset(request.organization).filter(
            scheduled_at__gte=values["start"], scheduled_at__lt=values["end"]
        )
        mapping = {
            "platform": "platform_id", "account": "social_account_id",
            "campaign": "platform_content__master_content__brief__campaign_id",
            "country": "platform_content__master_content__brief__target_country",
            "status": "status",
        }
        for name, field in mapping.items():
            if name in values:
                queryset = queryset.filter(**{field: values[name]})
        if "product" in values:
            queryset = queryset.filter(
                platform_content__master_content__brief__product_links__product_id=values["product"]
            )
        tasks = [
            task for task in queryset.distinct().order_by("scheduled_at", "id")
            if publish_task_is_consistent(task)
        ]
        zone = ZoneInfo(values["timezone"])
        grouped = defaultdict(list)
        for task in tasks:
            grouped[task.scheduled_at.astimezone(zone).date().isoformat()].append(
                PublishTaskSerializer(task).data
            )
        return Response(
            {
                "timezone": values["timezone"],
                "start": values["start"], "end": values["end"],
                "days": [
                    {"date": date, "entries": grouped[date]} for date in sorted(grouped)
                ],
            }
        )
