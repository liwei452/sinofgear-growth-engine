from django.db import DatabaseError
from django.db.models import Count, F
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.campaigns.models import Campaign
from apps.catalog.models import Product
from apps.identity.permissions import CanManageTracking, CanReadTracking
from apps.platforms.models import Platform
from apps.publishing.models import PublishedPost
from apps.publishing.services import consistent_publish_task_ids

from .models import ClickEvent, ShortLink, TrackingLink
from .privacy import PrivacyError
from .serializers import (
    AnalyticsFilterSerializer, ChannelSummaryEnvelopeSerializer, CursorFilterSerializer,
    ShortCursorEnvelopeSerializer, ShortLinkCreateSerializer, ShortLinkSerializer,
    TrackingCursorEnvelopeSerializer, TrackingErrorSerializer, TrackingLinkCreateSerializer,
    TrackingLinkSerializer, TrackingValidationErrorSerializer,
)
from .services import (
    TrackingConflict, _short_consistent, _tracking_consistent, create_short_link,
    create_tracking_link, record_click_event, resolve_active_short_link,
    validate_idempotency_key,
)


MAX_ANALYTICS_PUBLISH_TASKS = 200


def _validation(errors):
    return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


def _validated_query(request, serializer_class):
    repeated = {
        name: ["Provide this filter at most once."]
        for name in request.query_params
        if len(request.query_params.getlist(name)) > 1
    }
    serializer = serializer_class(data=request.query_params)
    valid = serializer.is_valid()
    if repeated or not valid:
        return None, _validation({**serializer.errors, **repeated})
    return serializer.validated_data, None


def _key(request):
    raw = request.headers.get("Idempotency-Key")
    if raw is None:
        raise ValidationError({"Idempotency-Key": ["This header is required."]})
    try:
        return validate_idempotency_key(raw)
    except TrackingConflict as exc:
        raise ValidationError({"Idempotency-Key": [str(exc)]}) from exc


def _domain_validation(exc):
    errors = exc.message_dict if hasattr(exc, "message_dict") else {"non_field_errors": exc.messages}
    return _validation(errors)


class TrackingPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _tracking_queryset(organization):
    return TrackingLink.objects.filter(organization=organization).select_related(
        "campaign", "platform", "product", "published_post__task",
        "published_post__platform_content__master_content__brief",
    )


def _short_queryset(organization):
    return ShortLink.objects.filter(organization=organization).select_related(
        "tracking_link__campaign", "tracking_link__platform", "tracking_link__product",
        "tracking_link__published_post__task",
        "tracking_link__published_post__platform_content__master_content__brief",
    )


def _tracking_link(organization, object_id):
    try:
        link = _tracking_queryset(organization).get(pk=object_id)
    except (TrackingLink.DoesNotExist, ValueError) as exc:
        raise Http404 from exc
    if not _tracking_consistent(link):
        raise Http404
    return link


def _short_link(organization, object_id):
    try:
        link = _short_queryset(organization).get(pk=object_id)
    except (ShortLink.DoesNotExist, ValueError) as exc:
        raise Http404 from exc
    if not _short_consistent(link):
        raise Http404
    return link


IDEMPOTENCY_PARAMETER = OpenApiParameter(
    "Idempotency-Key", OpenApiTypes.STR, location=OpenApiParameter.HEADER, required=True,
    description="Organization-scoped key of 1-128 visible ASCII characters.",
)


class TrackingLinkListView(APIView):
    serializer_class = TrackingLinkSerializer

    def get_permissions(self):
        return [(CanManageTracking if self.request.method == "POST" else CanReadTracking)()]

    @extend_schema(
        operation_id="tracking_links_list",
        parameters=[OpenApiParameter("cursor", OpenApiTypes.STR), OpenApiParameter("page_size", OpenApiTypes.INT)],
        responses={200: TrackingCursorEnvelopeSerializer},
    )
    def get(self, request):
        _values, error = _validated_query(request, CursorFilterSerializer)
        if error:
            return error
        paginator = TrackingPagination()
        page = paginator.paginate_queryset(_tracking_queryset(request.organization), request, view=self)
        safe = [link for link in page if _tracking_consistent(link)]
        return paginator.get_paginated_response(TrackingLinkSerializer(safe, many=True).data)

    @extend_schema(
        operation_id="tracking_links_create", request=TrackingLinkCreateSerializer,
        parameters=[IDEMPOTENCY_PARAMETER],
        responses={
            201: TrackingLinkSerializer,
            400: TrackingValidationErrorSerializer,
            409: TrackingErrorSerializer,
        },
    )
    def post(self, request):
        serializer = TrackingLinkCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        try:
            key = _key(request)
        except ValidationError as exc:
            return _validation(exc.message_dict)
        values = serializer.validated_data
        try:
            campaign = Campaign.objects.get(pk=values.pop("campaign_id"), organization=request.organization)
            product = Product.objects.get(pk=values.pop("product_id"), organization=request.organization)
            platform = Platform.objects.get(pk=values.pop("platform_id"))
            post = PublishedPost.objects.get(pk=values.pop("published_post_id"), organization=request.organization)
        except (Campaign.DoesNotExist, Product.DoesNotExist, Platform.DoesNotExist, PublishedPost.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        try:
            link = create_tracking_link(
                organization=request.organization, campaign=campaign, platform=platform,
                product=product, published_post=post, idempotency_key=key,
                actor=request.user, **values,
            )
        except ValidationError as exc:
            return _domain_validation(exc)
        except TrackingConflict as exc:
            return Response({"code": "tracking_conflict", "message": str(exc)}, status=409)
        return Response(TrackingLinkSerializer(_tracking_link(request.organization, link.id)).data, status=201)


class TrackingLinkDetailView(APIView):
    permission_classes = [CanReadTracking]
    serializer_class = TrackingLinkSerializer

    @extend_schema(operation_id="tracking_links_retrieve", responses={200: TrackingLinkSerializer})
    def get(self, request, link_id):
        return Response(TrackingLinkSerializer(_tracking_link(request.organization, link_id)).data)


class ShortLinkListView(APIView):
    serializer_class = ShortLinkSerializer

    def get_permissions(self):
        return [(CanManageTracking if self.request.method == "POST" else CanReadTracking)()]

    @extend_schema(
        operation_id="short_links_list",
        parameters=[OpenApiParameter("cursor", OpenApiTypes.STR), OpenApiParameter("page_size", OpenApiTypes.INT)],
        responses={200: ShortCursorEnvelopeSerializer},
    )
    def get(self, request):
        _values, error = _validated_query(request, CursorFilterSerializer)
        if error:
            return error
        paginator = TrackingPagination()
        page = paginator.paginate_queryset(_short_queryset(request.organization), request, view=self)
        safe = [link for link in page if _short_consistent(link)]
        return paginator.get_paginated_response(ShortLinkSerializer(safe, many=True).data)

    @extend_schema(
        operation_id="short_links_create", request=ShortLinkCreateSerializer,
        parameters=[IDEMPOTENCY_PARAMETER], responses={201: ShortLinkSerializer, 409: TrackingErrorSerializer},
    )
    def post(self, request):
        serializer = ShortLinkCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation(serializer.errors)
        try:
            key = _key(request)
        except ValidationError as exc:
            return _validation(exc.message_dict)
        tracking_link = _tracking_link(request.organization, serializer.validated_data["tracking_link_id"])
        try:
            short_link = create_short_link(
                organization=request.organization, tracking_link=tracking_link,
                idempotency_key=key, actor=request.user,
            )
        except TrackingConflict as exc:
            return Response({"code": "tracking_conflict", "message": str(exc)}, status=409)
        return Response(ShortLinkSerializer(_short_link(request.organization, short_link.id)).data, status=201)


class ShortLinkDetailView(APIView):
    permission_classes = [CanReadTracking]
    serializer_class = ShortLinkSerializer

    @extend_schema(operation_id="short_links_retrieve", responses={200: ShortLinkSerializer})
    def get(self, request, link_id):
        return Response(ShortLinkSerializer(_short_link(request.organization, link_id)).data)


class ChannelSummaryView(APIView):
    permission_classes = [CanReadTracking]
    serializer_class = ChannelSummaryEnvelopeSerializer

    @extend_schema(
        operation_id="analytics_channel_summary",
        parameters=[
            OpenApiParameter("start", OpenApiTypes.DATE, required=True),
            OpenApiParameter("end", OpenApiTypes.DATE, required=True),
            OpenApiParameter("campaign", OpenApiTypes.UUID),
            OpenApiParameter("platform", OpenApiTypes.UUID),
            OpenApiParameter("product", OpenApiTypes.UUID),
            OpenApiParameter("country", OpenApiTypes.STR),
            OpenApiParameter("limit", OpenApiTypes.INT),
            OpenApiParameter("offset", OpenApiTypes.INT),
            OpenApiParameter("page_size", OpenApiTypes.INT),
        ],
        responses={200: ChannelSummaryEnvelopeSerializer},
        description=(
            "Aggregate-only click counts grouped deterministically by date, campaign, platform, "
            "country and product. Date ranges contain at most 366 calendar days and reference at "
            "most 200 publishing tasks; no raw events or hashes are returned."
        ),
    )
    def get(self, request):
        values, error = _validated_query(request, AnalyticsFilterSerializer)
        if error:
            return error
        limit, offset = values.pop("limit"), values.pop("offset")
        queryset = ClickEvent.objects.filter(
            organization=request.organization,
            occurred_date__range=(values.pop("start"), values.pop("end")),
        )
        mapping = {
            "campaign": "campaign_id", "platform": "platform_id",
            "product": "product_id", "country": "country",
        }
        for name, field in mapping.items():
            if values.get(name):
                queryset = queryset.filter(**{field: values[name]})
        task_ids = list(
            queryset.order_by().values_list(
                "tracking_link__published_post__task_id", flat=True
            ).distinct()[: MAX_ANALYTICS_PUBLISH_TASKS + 1]
        )
        if len(task_ids) > MAX_ANALYTICS_PUBLISH_TASKS:
            return _validation({
                "date_range": [
                    "The selected range references too many publishing tasks; narrow the filters."
                ]
            })
        consistent_task_ids = consistent_publish_task_ids(
            organization=request.organization, task_ids=task_ids
        )
        queryset = queryset.filter(
            tracking_link__published_post__task_id__in=consistent_task_ids,
            tracking_link__organization=request.organization,
            short_link__organization=request.organization,
            campaign__organization=request.organization,
            product__organization=request.organization,
            short_link__tracking_link_id=F("tracking_link_id"),
            short_link__organization_id=F("organization_id"),
            tracking_link__organization_id=F("organization_id"),
            campaign_id=F("tracking_link__campaign_id"),
            platform_id=F("tracking_link__platform_id"),
            product_id=F("tracking_link__product_id"),
            tracking_fingerprint=F("tracking_link__request_fingerprint"),
            short_fingerprint=F("short_link__request_fingerprint"),
            short_code_snapshot=F("short_link__code"),
            publishing_fingerprint=F(
                "tracking_link__published_post__task__request_fingerprint"
            ),
            content_provenance_snapshot=F(
                "tracking_link__published_post__platform_content__provenance"
            ),
            master_content_provenance_snapshot=F(
                "tracking_link__published_post__platform_content__master_content__provenance"
            ),
            short_link__status__in=ShortLink.Status.values,
            short_link__code__regex=r"^s_[A-Za-z0-9_-]{12}$",
            tracking_link__published_post__organization_id=F("organization_id"),
            tracking_link__published_post__task__organization_id=F("organization_id"),
            tracking_link__published_post__attempt__organization_id=F("organization_id"),
            tracking_link__published_post__platform_content__organization_id=F(
                "organization_id"
            ),
            tracking_link__published_post__task__platform_content_id=F(
                "tracking_link__published_post__platform_content_id"
            ),
            tracking_link__published_post__task__social_account_id=F(
                "tracking_link__published_post__social_account_id"
            ),
            tracking_link__published_post__task__social_account__organization_id=F(
                "organization_id"
            ),
            tracking_link__published_post__social_account__organization_id=F(
                "organization_id"
            ),
            tracking_link__published_post__attempt__task_id=F(
                "tracking_link__published_post__task_id"
            ),
            tracking_link__published_post__task__platform_id=F("platform_id"),
            tracking_link__published_post__platform_content__platform_id=F("platform_id"),
            tracking_link__published_post__social_account__platform_id=F("platform_id"),
            tracking_link__published_post__platform_content__master_content__brief__campaign_id=F(
                "campaign_id"
            ),
            tracking_link__published_post__platform_content__master_content__brief__product_links__product_id=F(
                "product_id"
            ),
            tracking_link__published_post__task__status="SUCCEEDED",
            tracking_link__published_post__attempt__status="SUCCEEDED",
            tracking_link__published_post__attempt__outcome="SUCCEEDED",
            tracking_link__published_post__attempt__error__isnull=True,
            tracking_link__published_post__attempt__retry_at__isnull=True,
            tracking_link__published_post__platform_content__status="PUBLISHED",
            tracking_link__published_post__task__claim_token__isnull=True,
            tracking_link__published_post__task__last_error__isnull=True,
            tracking_link__published_post__task__retry_not_before__isnull=True,
            tracking_link__published_post__task__canceled_at__isnull=True,
            tracking_link__published_post__task__attempt_number=F(
                "tracking_link__published_post__attempt__number"
            ),
            tracking_link__published_post__task__content_version=F(
                "tracking_link__published_post__platform_content__version"
            ),
            tracking_link__published_post__attempt__request_fingerprint=F(
                "tracking_link__published_post__task__request_fingerprint"
            ),
            tracking_link__published_post__attempt__external_id=F(
                "tracking_link__published_post__external_id"
            ),
            tracking_link__published_post__task__started_at=F(
                "tracking_link__published_post__attempt__started_at"
            ),
            tracking_link__published_post__task__finished_at=F(
                "tracking_link__published_post__attempt__finished_at"
            ),
        ).filter(
            tracking_link__published_post__task__finished_at=F(
                "tracking_link__published_post__published_at"
            )
        )
        groups = queryset.values(
            "occurred_date", "campaign_id", "platform_id", "country", "product_id"
        ).annotate(clicks=Count("id")).order_by(
            "occurred_date", "campaign_id", "platform_id", "country", "product_id"
        )
        count = groups.count()
        rows = [
            {
                "date": row["occurred_date"], "campaign_id": row["campaign_id"],
                "platform_id": row["platform_id"], "country": row["country"],
                "product_id": row["product_id"], "clicks": row["clicks"],
            }
            for row in groups[offset : offset + limit]
        ]
        def page_url(new_offset):
            if new_offset < 0 or new_offset >= count:
                return None
            params = request.query_params.copy()
            params.pop("page_size", None)
            params["limit"] = limit
            params["offset"] = new_offset
            return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")
        return Response({
            "count": count,
            "next": page_url(offset + limit),
            "previous": page_url(max(0, offset - limit)) if offset else None,
            "results": ChannelSummaryEnvelopeSerializer().fields["results"].to_representation(rows),
        })


class PublicRedirectView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        operation_id="tracking_public_redirect",
        responses={302: OpenApiResponse(description="Recorded click; redirect to the exact canonical tracking URL."),
                   400: OpenApiResponse(description="Invalid privacy metadata; no click and no redirect."),
                   404: OpenApiResponse(description="Unknown, disabled, or inconsistent link."),
                   503: OpenApiResponse(description="Click could not be safely recorded; no redirect.")},
    )
    def get(self, request, code):
        short_link = resolve_active_short_link(code)
        if short_link is None:
            return HttpResponseNotFound()
        try:
            record_click_event(short_link=short_link, meta=request.META)
        except PrivacyError:
            return HttpResponse(status=400)
        except TrackingConflict:
            return HttpResponseNotFound()
        except DatabaseError:
            return HttpResponse(status=503)
        return HttpResponseRedirect(short_link.tracking_link.full_url)
