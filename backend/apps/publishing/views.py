from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Case, Count, IntegerField, Q, Subquery, Value, When
from django.http import Http404
from django.utils import timezone
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    PolymorphicProxySerializer,
    extend_schema,
)
from drf_spectacular.openapi import AutoSchema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.content.models import PlatformContent
from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManagePublishing, CanReadPublishing
from apps.platforms.models import SocialAccount

from .models import PublishTask
from .serializers import (
    CalendarFilterSerializer, EmptyActionSerializer, PublishCreateSerializer,
    ConfirmNotPublishedResolutionSerializer, ConfirmPublishedResolutionSerializer,
    PublishCalendarEnvelopeSerializer, PublishFilterSerializer,
    PublishMonitorEnvelopeSerializer, PublishMonitorFilterSerializer,
    PublishMonitorTaskSerializer,
    PublishResolutionSerializer,
    PublishingErrorSerializer, PublishTaskCursorEnvelopeSerializer,
    PublishTaskSerializer,
)
from .services import (
    PublishingConflict, cancel_publish_task, create_publish_task,
    publish_task_consistency_queryset, publish_task_is_consistent,
    retry_publish_task, run_publish_task_now, validate_idempotency_key,
)
from .reconciliation import reconcile_publish_task
from .resolution import resolve_publish_task


MAX_CALENDAR_ENTRIES = 200


class RequiredPolymorphicRequestSchema(AutoSchema):
    def _get_request_for_media_type(self, serializer, direction="request"):
        schema, required = super()._get_request_for_media_type(serializer, direction)
        if isinstance(serializer, PolymorphicProxySerializer):
            required = True
        return schema, required


class PublishPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


class PublishMonitorPagination(PublishPagination):
    ordering = ("_monitor_priority", "-created_at", "-id")


def _safe_queryset(organization):
    return publish_task_consistency_queryset(organization)


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
            "recovery_action": "请刷新任务或重新连接账号后重试。",
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


@extend_schema(tags=["PublishTasks"])
class PublishTaskListView(APIView):
    serializer_class = PublishTaskSerializer

    def get_permissions(self):
        classes = [CanManagePublishing] if self.request.method == "POST" else [CanReadPublishing]
        return [permission() for permission in classes]

    @extend_schema(
        operation_id="publish_task_list",
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=PublishTask.Status.values),
            OpenApiParameter("platform", OpenApiTypes.UUID),
            OpenApiParameter("account", OpenApiTypes.UUID),
            OpenApiParameter("content", OpenApiTypes.UUID),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
        ],
        responses={200: PublishTaskCursorEnvelopeSerializer},
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
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation({"cursor": ["Invalid or expired cursor."]})
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


MONITOR_GROUP_STATUSES = {
    "ATTENTION": (PublishTask.Status.NEEDS_ATTENTION,),
    "PROVIDER": (PublishTask.Status.SUBMITTED, PublishTask.Status.SUBMISSION_UNKNOWN),
    "FAILED": (PublishTask.Status.FAILED,),
    "WAITING": (
        PublishTask.Status.SCHEDULED, PublishTask.Status.QUEUED,
        PublishTask.Status.RUNNING,
    ),
    "COMPLETED": (PublishTask.Status.SUCCEEDED,),
}


@extend_schema(tags=["PublishTasks"])
class PublishTaskMonitorView(APIView):
    permission_classes = [CanReadPublishing]
    serializer_class = PublishMonitorTaskSerializer

    @extend_schema(
        operation_id="publish_task_monitor",
        parameters=[
            OpenApiParameter("group", OpenApiTypes.STR, enum=list(MONITOR_GROUP_STATUSES)),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
        ],
        responses={200: PublishMonitorEnvelopeSerializer},
    )
    def get(self, request):
        values, error = _validated_query(request, PublishMonitorFilterSerializer)
        if error:
            return error
        base = PublishTask.objects.filter(organization=request.organization)
        now = timezone.now()
        local_today = timezone.localdate(now)
        day_start = timezone.make_aware(datetime.combine(local_today, time.min))
        day_end = day_start + timedelta(days=1)
        summary = base.aggregate(
            attention_count=Count("id", filter=Q(status=PublishTask.Status.NEEDS_ATTENTION)),
            provider_pending_count=Count("id", filter=Q(status__in=MONITOR_GROUP_STATUSES["PROVIDER"])),
            failed_count=Count("id", filter=Q(status=PublishTask.Status.FAILED)),
            waiting_count=Count("id", filter=Q(status__in=MONITOR_GROUP_STATUSES["WAITING"])),
            today_succeeded_count=Count(
                "id", filter=Q(
                    status=PublishTask.Status.SUCCEEDED,
                    finished_at__gte=day_start, finished_at__lt=day_end,
                )
            ),
        )
        queryset = _safe_queryset(request.organization)
        group = values.get("group")
        if group:
            queryset = queryset.filter(status__in=MONITOR_GROUP_STATUSES[group])
            if group == "COMPLETED":
                queryset = queryset.filter(
                    finished_at__gte=day_start, finished_at__lt=day_end
                )
        else:
            recent_successes = base.filter(status=PublishTask.Status.SUCCEEDED).order_by(
                "-created_at", "-id"
            ).values("id")[:5]
            queryset = queryset.filter(
                Q(status__in=sum(MONITOR_GROUP_STATUSES.values(), ()))
                & (~Q(status=PublishTask.Status.SUCCEEDED) | Q(id__in=Subquery(recent_successes)))
            )
        queryset = queryset.annotate(
            _monitor_priority=Case(
                When(status=PublishTask.Status.NEEDS_ATTENTION, then=Value(0)),
                When(status__in=MONITOR_GROUP_STATUSES["PROVIDER"], then=Value(1)),
                When(status=PublishTask.Status.FAILED, then=Value(2)),
                When(status__in=MONITOR_GROUP_STATUSES["WAITING"], then=Value(3)),
                When(status=PublishTask.Status.SUCCEEDED, then=Value(4)),
                default=Value(5), output_field=IntegerField(),
            )
        )
        paginator = PublishMonitorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation({"cursor": ["Invalid or expired cursor."]})
        safe = [task for task in page if publish_task_is_consistent(task)]
        page_response = paginator.get_paginated_response(
            PublishMonitorTaskSerializer(safe, many=True).data
        ).data
        return Response({"summary": summary, **page_response})


class PublishScheduleView(PublishTaskListView):
    http_method_names = ["post", "options"]

    @extend_schema(
        request=PublishCreateSerializer,
        parameters=[OpenApiParameter(
            "Idempotency-Key", OpenApiTypes.STR, location=OpenApiParameter.HEADER, required=True,
        )],
        responses={201: PublishTaskSerializer, 409: PublishingErrorSerializer},
    )
    def post(self, request):
        return super().post(request)


@extend_schema(tags=["PublishTasks"])
class PublishTaskDetailView(APIView):
    permission_classes = [CanReadPublishing]
    serializer_class = PublishTaskSerializer

    def get(self, request, task_id):
        return Response(PublishTaskSerializer(_task(request.organization, task_id)).data)


@extend_schema(tags=["PublishTasks"])
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
            elif self.action == "run":
                task = run_publish_task_now(task, actor=request.user)
            else:
                task = cancel_publish_task(task, actor=request.user)
        except PublishingConflict as exc:
            return _conflict(exc)
        return Response(PublishTaskSerializer(_task(request.organization, task.id)).data)


class PublishCancelView(PublishActionView):
    action = "cancel"


class PublishRetryView(PublishActionView):
    action = "retry"


class PublishRunView(PublishActionView):
    action = "run"


@extend_schema(tags=["PublishTasks"])
class PublishReconcileView(APIView):
    permission_classes = [CanManagePublishing]
    serializer_class = EmptyActionSerializer

    @extend_schema(
        request=EmptyActionSerializer,
        responses={
            200: PublishTaskSerializer,
            409: PublishingErrorSerializer,
            429: PublishingErrorSerializer,
            502: PublishingErrorSerializer,
            503: PublishingErrorSerializer,
        },
    )
    def post(self, request, task_id):
        serializer = EmptyActionSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        _task(request.organization, task_id)
        try:
            task = reconcile_publish_task(
                task_id, organization=request.organization, actor=request.user
            )
        except PublishingConflict as exc:
            return _conflict(exc)
        error_code = task.reconciliation_error_code
        status_mapping = {
            "BUFFER_AUTHENTICATION_REQUIRED": status.HTTP_409_CONFLICT,
            "BUFFER_RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
            "BUFFER_PROVIDER_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
        }
        if error_code in status_mapping and task.status in {
            PublishTask.Status.SUBMITTED,
            PublishTask.Status.SUBMISSION_UNKNOWN,
        }:
            return Response(
                {
                    "code": error_code.lower(),
                    "message": "Buffer reconciliation could not complete safely.",
                    "recovery_action": "Wait until the recorded next reconciliation time or reconnect Buffer.",
                },
                status=status_mapping[error_code],
            )
        return Response(PublishTaskSerializer(_task(request.organization, task.id)).data)


@extend_schema(tags=["PublishTasks"])
class PublishResolveView(APIView):
    permission_classes = [CanManagePublishing]
    serializer_class = PublishResolutionSerializer
    schema = RequiredPolymorphicRequestSchema()

    @extend_schema(
        request=PolymorphicProxySerializer(
            component_name="PublishResolutionRequest",
            serializers={
                "CONFIRM_PUBLISHED": ConfirmPublishedResolutionSerializer,
                "CONFIRM_NOT_PUBLISHED": ConfirmNotPublishedResolutionSerializer,
            },
            resource_type_field_name="resolution",
            required=True,
        ),
        responses={200: PublishTaskSerializer, 409: PublishingErrorSerializer},
    )
    def post(self, request, task_id):
        serializer = PublishResolutionSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        task = _task(request.organization, task_id)
        try:
            task = resolve_publish_task(
                task,
                resolution=serializer.validated_data["resolution"],
                provider_post_id=serializer.validated_data.get("provider_post_id", ""),
                actor=request.user,
                organization=request.organization,
            )
        except PublishingConflict as exc:
            return _conflict(exc)
        return Response(PublishTaskSerializer(_task(request.organization, task.id)).data)


@extend_schema(tags=["PublishTasks"])
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
        responses={200: PublishCalendarEnvelopeSerializer},
        description=(
            "Returns at most 200 tasks ordered by UTC scheduled time and ID, "
            "grouped into IANA local display dates. metadata.truncated reports "
            "whether more matching database rows exist."
        ),
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
        candidates = list(
            queryset.distinct().order_by("scheduled_at", "id")[
                :MAX_CALENDAR_ENTRIES + 1
            ]
        )
        tasks = [
            task for task in candidates if publish_task_is_consistent(task)
        ][:MAX_CALENDAR_ENTRIES]
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
                "metadata": {
                    "max_entries": MAX_CALENDAR_ENTRIES,
                    "returned_entries": len(tasks),
                    "truncated": len(candidates) > MAX_CALENDAR_ENTRIES,
                },
                "days": [
                    {"date": date, "entries": grouped[date]} for date in sorted(grouped)
                ],
            }
        )
