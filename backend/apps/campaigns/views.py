from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Prefetch
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import (
    CanManageCampaigns,
    CanReadCampaigns,
    CanReviewCampaigns,
)

from .models import (
    Campaign,
    CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
)
from .serializers import (
    CampaignCreateSerializer,
    CampaignFilterSerializer,
    CampaignListSerializer,
    CampaignPatchSerializer,
    CampaignSerializer,
    ContentBriefCreateSerializer,
    ContentBriefFilterSerializer,
    ContentBriefListSerializer,
    ContentBriefPatchSerializer,
    ContentBriefSerializer,
    ErrorSerializer,
    ValidationErrorSerializer,
)
from .services import mark_content_brief_ready, revise_content_brief


ERRORS = {403: ErrorSerializer, 404: ErrorSerializer}


def _error_values(value):
    if isinstance(value, dict):
        return {key: _error_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_error_values(item) for item in value]
    return str(value)


def _validation_response(error):
    if isinstance(error, DjangoValidationError):
        values = error.message_dict if hasattr(error, "message_dict") else {
            "non_field_errors": error.messages
        }
    elif isinstance(error, IntegrityError):
        values = {"non_field_errors": ["Duplicate relationship selection."]}
    else:
        values = error
    return Response({"errors": _error_values(values)}, status=status.HTTP_400_BAD_REQUEST)


def _campaign_queryset(organization):
    return Campaign.objects.filter(organization=organization).prefetch_related(
        Prefetch(
            "product_links",
            queryset=CampaignProduct.objects.filter(organization=organization).order_by("product_id", "id"),
            to_attr="safe_product_links",
        )
    )


def _brief_queryset(organization):
    return ContentBrief.objects.filter(organization=organization).select_related(
        "campaign", "created_by", "reviewed_by"
    ).prefetch_related(
        Prefetch("product_links", queryset=ContentBriefProduct.objects.filter(organization=organization).order_by("product_id", "id"), to_attr="safe_product_links"),
        Prefetch("asset_links", queryset=ContentBriefAsset.objects.filter(organization=organization).order_by("asset_id", "id"), to_attr="safe_asset_links"),
        Prefetch("platform_links", queryset=ContentBriefPlatform.objects.filter(organization=organization).order_by("platform_id", "id"), to_attr="safe_platform_links"),
        Prefetch("concept_links", queryset=ContentBriefConceptLink.objects.filter(organization=organization).order_by("role", "concept_id", "id"), to_attr="safe_concept_links"),
    )


def _get_campaign(organization, object_id):
    try:
        return _campaign_queryset(organization).get(pk=object_id)
    except Campaign.DoesNotExist as error:
        raise Http404 from error


def _get_brief(organization, object_id):
    try:
        return _brief_queryset(organization).get(pk=object_id)
    except ContentBrief.DoesNotExist as error:
        raise Http404 from error


def _validate_filters(request, serializer_class, names):
    repeated = {
        name: ["Provide this filter at most once."]
        for name in names
        if len(request.query_params.getlist(name)) > 1
    }
    if repeated:
        return None, _validation_response(repeated)
    serializer = serializer_class(data=request.query_params)
    if not serializer.is_valid():
        return None, _validation_response(serializer.errors)
    return serializer.validated_data, None


class CampaignCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


class BriefCursorPagination(CampaignCursorPagination):
    pass


class CampaignListView(APIView):
    def get_permissions(self):
        return [(CanReadCampaigns if self.request.method == "GET" else CanManageCampaigns)()]

    @extend_schema(
        operation_id="campaigns_list",
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=Campaign.Status.values),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            OpenApiParameter("page_size", OpenApiTypes.INT),
        ],
        responses={200: CampaignListSerializer, 400: ValidationErrorSerializer, 403: ErrorSerializer},
    )
    def get(self, request: Request):
        values, error = _validate_filters(
            request, CampaignFilterSerializer, ("status", "cursor", "page_size")
        )
        if error:
            return error
        queryset = _campaign_queryset(request.organization)
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        paginator = CampaignCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset.order_by("-created_at", "-id"), request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(CampaignSerializer(page, many=True).data)

    @extend_schema(
        operation_id="campaigns_create", request=CampaignCreateSerializer,
        responses={201: CampaignSerializer, 400: ValidationErrorSerializer, 403: ErrorSerializer},
    )
    def post(self, request: Request):
        serializer = CampaignCreateSerializer(data=request.data, context={"organization": request.organization})
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            campaign = serializer.save()
        except (DjangoValidationError, IntegrityError) as error:
            return _validation_response(error)
        return Response(CampaignSerializer(_get_campaign(request.organization, campaign.id)).data, status=201)


class CampaignDetailView(APIView):
    def get_permissions(self):
        return [(CanReadCampaigns if self.request.method == "GET" else CanManageCampaigns)()]

    @extend_schema(operation_id="campaigns_retrieve", responses={200: CampaignSerializer, **ERRORS})
    def get(self, request, campaign_id):
        return Response(CampaignSerializer(_get_campaign(request.organization, campaign_id)).data)

    @extend_schema(operation_id="campaigns_partial_update", request=CampaignPatchSerializer, responses={200: CampaignSerializer, 400: ValidationErrorSerializer, **ERRORS})
    def patch(self, request, campaign_id):
        campaign = _get_campaign(request.organization, campaign_id)
        serializer = CampaignPatchSerializer(campaign, data=request.data, partial=True)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            serializer.save()
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(CampaignSerializer(_get_campaign(request.organization, campaign_id)).data)

    @extend_schema(operation_id="campaigns_delete", responses={204: None, **ERRORS})
    def delete(self, request, campaign_id):
        campaign = _get_campaign(request.organization, campaign_id)
        campaign.status = Campaign.Status.ARCHIVED
        campaign.save(update_fields=["status", "updated_at"])
        return Response(status=204)


class ContentBriefListView(APIView):
    def get_permissions(self):
        return [(CanReadCampaigns if self.request.method == "GET" else CanManageCampaigns)()]

    @extend_schema(
        operation_id="content_briefs_list",
        parameters=[
            OpenApiParameter("status", OpenApiTypes.STR, enum=ContentBrief.Status.values),
            OpenApiParameter("campaign", OpenApiTypes.UUID),
            OpenApiParameter("cursor", OpenApiTypes.STR),
            OpenApiParameter("page_size", OpenApiTypes.INT),
        ],
        responses={200: ContentBriefListSerializer, 400: ValidationErrorSerializer, 403: ErrorSerializer},
    )
    def get(self, request):
        values, error = _validate_filters(
            request, ContentBriefFilterSerializer, ("status", "campaign", "cursor", "page_size")
        )
        if error:
            return error
        queryset = _brief_queryset(request.organization)
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        if "campaign" in values:
            queryset = queryset.filter(campaign_id=values["campaign"])
        paginator = BriefCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset.order_by("-created_at", "-id"), request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(ContentBriefSerializer(page, many=True).data)

    @extend_schema(operation_id="content_briefs_create", request=ContentBriefCreateSerializer, responses={201: ContentBriefSerializer, 400: ValidationErrorSerializer, 403: ErrorSerializer})
    def post(self, request):
        serializer = ContentBriefCreateSerializer(
            data=request.data,
            context={"organization": request.organization, "creator": request.user},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            brief = serializer.save()
        except (DjangoValidationError, IntegrityError) as error:
            return _validation_response(error)
        return Response(ContentBriefSerializer(_get_brief(request.organization, brief.id)).data, status=201)


class ContentBriefDetailView(APIView):
    def get_permissions(self):
        return [(CanReadCampaigns if self.request.method == "GET" else CanManageCampaigns)()]

    @extend_schema(operation_id="content_briefs_retrieve", responses={200: ContentBriefSerializer, **ERRORS})
    def get(self, request, brief_id):
        return Response(ContentBriefSerializer(_get_brief(request.organization, brief_id)).data)

    @extend_schema(operation_id="content_briefs_partial_update", request=ContentBriefPatchSerializer, responses={200: ContentBriefSerializer, 400: ValidationErrorSerializer, **ERRORS})
    def patch(self, request, brief_id):
        brief = _get_brief(request.organization, brief_id)
        serializer = ContentBriefPatchSerializer(brief, data=request.data, partial=True)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            serializer.save()
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(ContentBriefSerializer(_get_brief(request.organization, brief_id)).data)

    @extend_schema(operation_id="content_briefs_delete", responses={400: ValidationErrorSerializer, **ERRORS})
    def delete(self, request, brief_id):
        _get_brief(request.organization, brief_id)
        return _validation_response({"status": ["Content brief history cannot be deleted."]})


class ContentBriefReadyView(APIView):
    permission_classes = [CanReviewCampaigns]

    @extend_schema(operation_id="content_briefs_mark_ready", request=None, responses={200: ContentBriefSerializer, 400: ValidationErrorSerializer, **ERRORS})
    def post(self, request, brief_id):
        brief = _get_brief(request.organization, brief_id)
        try:
            mark_content_brief_ready(brief.id, reviewer=request.user)
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(ContentBriefSerializer(_get_brief(request.organization, brief_id)).data)


class ContentBriefRevisionView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(operation_id="content_briefs_create_revision", request=None, responses={201: ContentBriefSerializer, 400: ValidationErrorSerializer, **ERRORS})
    def post(self, request, brief_id):
        source = _get_brief(request.organization, brief_id)
        try:
            revision = revise_content_brief(source.id, creator=request.user)
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(ContentBriefSerializer(_get_brief(request.organization, revision.id)).data, status=201)
