from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.models import Prefetch
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError
from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageAssets, CanReadAssets

from .models import AssetProductLink, MaterialAsset
from .serializers import (
    AssetDownloadSerializer,
    AssetErrorSerializer,
    AssetFilterSerializer,
    AssetListSerializer,
    AssetProductLinkInputSerializer,
    AssetUploadSerializer,
    AssetValidationErrorSerializer,
    MaterialAssetSerializer,
    AssetUnderstandingResultSerializer,
    AssetUnderstandingRetrySerializer,
    AssetUnderstandingStartSerializer,
    ProductEvidenceFactReviewSerializer,
    ProductEvidenceFactSerializer,
)
from .models import ProductEvidenceFact
from .services import AssetUploadError, link_asset_to_product, set_asset_archived
from .storage import get_object_storage
from .understanding import (
    AssetUnderstandingError,
    load_understanding_result,
    retry_understanding,
    review_fact,
    start_understanding,
)


FILTER_PARAMETERS = [
    OpenApiParameter(
        "type",
        OpenApiTypes.STR,
        enum=MaterialAsset.AssetType.values,
        description="Exact asset type. May be supplied at most once; invalid values return 400.",
    ),
    OpenApiParameter(
        "status",
        OpenApiTypes.STR,
        enum=MaterialAsset.Status.values,
        description="Exact asset status. May be supplied at most once; invalid values return 400.",
    ),
    OpenApiParameter(
        "product",
        OpenApiTypes.UUID,
        description="Organization-scoped product UUID. May be supplied at most once.",
    ),
    OpenApiParameter(
        "tag",
        OpenApiTypes.STR,
        description="Exact case-sensitive tag. May be supplied at most once.",
    ),
    OpenApiParameter(
        "cursor",
        OpenApiTypes.STR,
        description="Opaque stable cursor; generated links preserve all active filters.",
    ),
    bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
]
ERROR_RESPONSES = {403: AssetErrorSerializer, 404: AssetErrorSerializer}


def _error_values(error):
    if isinstance(error, dict):
        return {key: _error_values(value) for key, value in error.items()}
    if isinstance(error, (list, tuple)):
        return [_error_values(value) for value in error]
    return str(error)


def _validation_response(errors) -> Response:
    if isinstance(errors, DjangoValidationError):
        errors = (
            errors.message_dict
            if hasattr(errors, "message_dict")
            else {"non_field_errors": errors.messages}
        )
    return Response(
        {"errors": _error_values(errors)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _safe_product_links(organization):
    return AssetProductLink.objects.filter(
        organization=organization,
        asset__organization=organization,
        product__organization=organization,
    ).select_related("product")


def _asset_queryset(organization):
    return MaterialAsset.objects.filter(organization=organization).prefetch_related(
        Prefetch(
            "product_links",
            queryset=_safe_product_links(organization),
            to_attr="safe_product_links",
        )
    )


def _get_asset(organization, asset_id) -> MaterialAsset:
    try:
        return _asset_queryset(organization).get(pk=asset_id)
    except MaterialAsset.DoesNotExist as error:
        raise Http404 from error


class AssetCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


@extend_schema(tags=["Assets"])
class AssetListView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        return [(CanReadAssets if self.request.method == "GET" else CanManageAssets)()]

    @extend_schema(
        operation_id="assets_list",
        parameters=FILTER_PARAMETERS,
        responses={
            200: AssetListSerializer,
            400: AssetValidationErrorSerializer,
            403: AssetErrorSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        repeated = {
            name: ["Provide this filter at most once."]
            for name in ("type", "status", "product", "tag", "page_size", "cursor")
            if len(request.query_params.getlist(name)) > 1
        }
        if repeated:
            return _validation_response(repeated)
        filters = AssetFilterSerializer(data=request.query_params)
        if not filters.is_valid():
            return _validation_response(filters.errors)
        values = filters.validated_data
        queryset = _asset_queryset(request.organization)
        if "status" not in values:
            queryset = queryset.exclude(status=MaterialAsset.Status.ARCHIVED)
        if "type" in values:
            queryset = queryset.filter(asset_type=values["type"])
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        if "product" in values:
            queryset = queryset.filter(
                product_links__organization=request.organization,
                product_links__product_id=values["product"],
                product_links__product__organization=request.organization,
            )
        if "tag" in values:
            if connection.vendor == "sqlite":
                tagged_ids = [
                    asset_id
                    for asset_id, tags in queryset.values_list("id", "tags")
                    if values["tag"] in tags
                ]
                queryset = queryset.filter(pk__in=tagged_ids)
            else:
                queryset = queryset.filter(tags__contains=[values["tag"]])
        queryset = queryset.distinct().order_by("-created_at", "-id")
        paginator = AssetCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(MaterialAssetSerializer(page, many=True).data)

    @extend_schema(
        operation_id="assets_create",
        request=AssetUploadSerializer,
        responses={
            200: MaterialAssetSerializer,
            201: MaterialAssetSerializer,
            400: AssetValidationErrorSerializer,
            403: AssetErrorSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = AssetUploadSerializer(
            data=request.data,
            context={"organization": request.organization, "creator": request.user},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            asset = serializer.save()
        except (AssetUploadError, DjangoValidationError) as error:
            return _validation_response({"file": [str(error)]})
        was_created = getattr(asset, "_upload_created", True)
        asset = _asset_queryset(request.organization).get(pk=asset.pk)
        response_status = status.HTTP_201_CREATED if was_created else status.HTTP_200_OK
        return Response(MaterialAssetSerializer(asset).data, status=response_status)


@extend_schema(tags=["Assets"])
class AssetDetailView(APIView):
    permission_classes = [CanReadAssets]

    @extend_schema(
        operation_id="assets_retrieve",
        responses={200: MaterialAssetSerializer, **ERROR_RESPONSES},
    )
    def get(self, request: Request, asset_id) -> Response:
        return Response(MaterialAssetSerializer(_get_asset(request.organization, asset_id)).data)


@extend_schema(tags=["Assets"])
class AssetArchiveView(APIView):
    permission_classes = [CanManageAssets]
    serializer_class = MaterialAssetSerializer

    @extend_schema(request=None, responses={200: MaterialAssetSerializer, **ERROR_RESPONSES})
    def post(self, request: Request, asset_id) -> Response:
        if request.data:
            return _validation_response({name: ["Unknown field."] for name in request.data})
        asset = set_asset_archived(
            asset=_get_asset(request.organization, asset_id), actor=request.user, archived=True
        )
        return Response(MaterialAssetSerializer(_get_asset(request.organization, asset.id)).data)


@extend_schema(tags=["Assets"])
class AssetRestoreView(APIView):
    permission_classes = [CanManageAssets]
    serializer_class = MaterialAssetSerializer

    @extend_schema(request=None, responses={200: MaterialAssetSerializer, **ERROR_RESPONSES})
    def post(self, request: Request, asset_id) -> Response:
        if request.data:
            return _validation_response({name: ["Unknown field."] for name in request.data})
        asset = set_asset_archived(
            asset=_get_asset(request.organization, asset_id), actor=request.user, archived=False
        )
        return Response(MaterialAssetSerializer(_get_asset(request.organization, asset.id)).data)


@extend_schema(tags=["Assets"])
class AssetLinkProductView(APIView):
    permission_classes = [CanManageAssets]

    @extend_schema(
        operation_id="assets_link_product",
        request=AssetProductLinkInputSerializer,
        responses={
            200: MaterialAssetSerializer,
            201: MaterialAssetSerializer,
            400: AssetValidationErrorSerializer,
            **ERROR_RESPONSES,
        },
    )
    def post(self, request: Request, asset_id) -> Response:
        asset = _get_asset(request.organization, asset_id)
        serializer = AssetProductLinkInputSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            product = Product.objects.get(
                pk=serializer.validated_data["product_id"],
                organization=request.organization,
            )
        except Product.DoesNotExist as error:
            raise Http404 from error
        try:
            _, created = link_asset_to_product(asset=asset, product=product)
        except DjangoValidationError as error:
            return _validation_response(error)
        refreshed = _asset_queryset(request.organization).get(pk=asset.pk)
        return Response(
            MaterialAssetSerializer(refreshed).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@extend_schema(tags=["Assets"])
class AssetDownloadURLView(APIView):
    permission_classes = [CanReadAssets]

    @extend_schema(
        operation_id="assets_download_url",
        request=None,
        responses={200: AssetDownloadSerializer, **ERROR_RESPONSES},
    )
    def post(self, request: Request, asset_id) -> Response:
        asset = _get_asset(request.organization, asset_id)
        expires_in = 300
        url = get_object_storage().presigned_download_url(
            asset.storage_key,
            expires_in,
        )
        return Response({"url": url, "expires_in": expires_in})


def _serialize_understanding(result) -> dict:
    return AssetUnderstandingResultSerializer(
        {
            "job": result.job,
            "facts": result.facts,
            "warnings": list(result.warnings),
            "is_partial": result.is_partial,
            "provider_label": result.provider_label,
        }
    ).data


def _latest_understanding_job(organization, asset_id):
    return (
        Job.objects.filter(
            organization=organization,
            type=Job.Type.ASSET_UNDERSTAND,
            input_snapshot__asset_id=str(asset_id),
        )
        .order_by("-created_at", "-id")
        .first()
    )


@extend_schema(tags=["Assets"])
class AssetUnderstandingView(APIView):
    def get_permissions(self):
        return [(CanReadAssets if self.request.method == "GET" else CanManageAssets)()]

    @extend_schema(
        operation_id="assets_understanding_retrieve",
        responses={200: AssetUnderstandingResultSerializer, **ERROR_RESPONSES},
    )
    def get(self, request: Request, asset_id) -> Response:
        _get_asset(request.organization, asset_id)
        job = _latest_understanding_job(request.organization, asset_id)
        if job is None:
            raise Http404
        return Response(_serialize_understanding(load_understanding_result(job)))

    @extend_schema(
        operation_id="assets_understanding_create",
        request=AssetUnderstandingStartSerializer,
        responses={
            200: AssetUnderstandingResultSerializer,
            400: AssetValidationErrorSerializer,
            **ERROR_RESPONSES,
        },
    )
    def post(self, request: Request, asset_id) -> Response:
        asset = _get_asset(request.organization, asset_id)
        serializer = AssetUnderstandingStartSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            product = Product.objects.get(
                pk=serializer.validated_data["product_id"],
                organization=request.organization,
            )
        except Product.DoesNotExist as error:
            raise Http404 from error
        try:
            result = start_understanding(
                asset=asset,
                product=product,
                actor=request.user,
                external_text_consent=serializer.validated_data["external_text_consent"],
            )
        except (AssetUnderstandingError, DjangoValidationError) as error:
            return _validation_response({"non_field_errors": [str(error)]})
        return Response(_serialize_understanding(result))


@extend_schema(tags=["Assets"])
class AssetUnderstandingRetryView(APIView):
    permission_classes = [CanManageAssets]

    @extend_schema(
        operation_id="assets_understanding_retry",
        request=AssetUnderstandingRetrySerializer,
        responses={200: AssetUnderstandingResultSerializer, 409: AssetErrorSerializer, **ERROR_RESPONSES},
    )
    def post(self, request: Request, asset_id) -> Response:
        _get_asset(request.organization, asset_id)
        serializer = AssetUnderstandingRetrySerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        job = _latest_understanding_job(request.organization, asset_id)
        if job is None:
            raise Http404
        try:
            result = retry_understanding(
                job=job,
                actor=request.user,
                external_text_consent=serializer.validated_data["external_text_consent"],
            )
        except AssetUnderstandingError as error:
            return _validation_response({"non_field_errors": [str(error)]})
        except JobConflictError as error:
            return Response({"detail": str(error)}, status=status.HTTP_409_CONFLICT)
        return Response(_serialize_understanding(result))


@extend_schema(tags=["Assets"])
class ProductEvidenceFactReviewView(APIView):
    permission_classes = [CanManageAssets]

    @extend_schema(
        operation_id="assets_fact_review",
        request=ProductEvidenceFactReviewSerializer,
        responses={200: ProductEvidenceFactSerializer, 400: AssetValidationErrorSerializer, **ERROR_RESPONSES},
    )
    def post(self, request: Request, fact_id) -> Response:
        try:
            fact = ProductEvidenceFact.objects.get(
                pk=fact_id,
                organization=request.organization,
                asset__organization=request.organization,
                product__organization=request.organization,
                job__organization=request.organization,
            )
        except ProductEvidenceFact.DoesNotExist as error:
            raise Http404 from error
        serializer = ProductEvidenceFactReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        reviewed = review_fact(
            fact=fact,
            decision=serializer.validated_data["decision"],
            actor=request.user,
            note=serializer.validated_data["note"],
        )
        return Response(ProductEvidenceFactSerializer(reviewed).data)
