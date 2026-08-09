import re
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.http import Http404
from drf_spectacular.utils import (
    OpenApiParameter,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageProducts, CanReadProducts

from apps.knowledge.models import KnowledgeConcept

from .models import (
    ROLE_CONCEPT_TYPES,
    Product,
    ProductConceptLink,
    compatible_link_types_q,
)
from .serializers import (
    ProductCreateSerializer,
    ProductErrorSerializer,
    ProductFilterSerializer,
    ProductListSerializer,
    ProductPatchSerializer,
    ProductPreconditionErrorSerializer,
    ProductSerializer,
    ProductValidationErrorSerializer,
    ProductVersionConflictSerializer,
)


ERROR_RESPONSES = {
    403: ProductErrorSerializer,
    404: ProductErrorSerializer,
}


FILTER_PARAMETERS = [
    OpenApiParameter(
        name=name,
        type=str,
        location=OpenApiParameter.QUERY,
        required=False,
        description=(
            "Resolve one visible APPROVED concept by UUID or exact case-sensitive code, then "
            f"match current active {role} links. Ambiguous and repeated values return 400."
        ),
    )
    for name, role in (
        ("type", ProductConceptLink.Role.TYPE),
        ("material", ProductConceptLink.Role.MATERIAL),
        ("application", ProductConceptLink.Role.APPLICATION),
    )
] + [
    OpenApiParameter(
        name="status",
        type=str,
        enum=Product.Status.values,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Exact product status: DRAFT, ACTIVE, or ARCHIVED.",
    ),
    OpenApiParameter(
        name="cursor",
        type=str,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Opaque cursor from the next or previous page URL.",
    ),
    OpenApiParameter(
        name="page_size",
        type=int,
        location=OpenApiParameter.QUERY,
        required=False,
        description="Requested page size. Defaults to 20 and is capped at 50.",
    ),
]


IF_MATCH_PARAMETER = OpenApiParameter(
    name="If-Match",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Required strong ETag containing the quoted positive integer version, for example "3".',
)


ETAG_RESPONSE_PARAMETER = OpenApiParameter(
    name="ETag",
    type=str,
    location=OpenApiParameter.HEADER,
    response=True,
    required=True,
    description='Strong ETag containing the quoted current product version, for example "3".',
)


class ProductVersionConflict(Exception):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version


def _product_queryset(organization) -> QuerySet[Product]:
    safe_links = (
        ProductConceptLink.objects.active()
        .filter(
            organization=organization,
            product__organization=organization,
            concept__status=KnowledgeConcept.Status.APPROVED,
        )
        .filter(
            Q(concept__organization__isnull=True)
            | Q(concept__organization=organization)
        )
        .filter(compatible_link_types_q())
        .select_related("concept")
        .order_by("role", "concept__code", "id")
    )
    return Product.objects.filter(organization=organization).prefetch_related(
        Prefetch(
            "concept_links",
            queryset=safe_links,
            to_attr="active_concept_links",
        )
    )


def _error_values(error) -> object:
    if isinstance(error, dict):
        return {key: _error_values(value) for key, value in error.items()}
    if isinstance(error, (list, tuple)):
        return [_error_values(value) for value in error]
    return str(error)


def _validation_response(error) -> Response:
    if isinstance(error, DjangoValidationError):
        if hasattr(error, "message_dict"):
            errors = error.message_dict
        else:
            errors = {"non_field_errors": error.messages}
    elif isinstance(error, IntegrityError):
        errors = {"concept_links": ["Duplicate product role/concept pairs are not allowed."]}
    else:
        errors = error
    return Response(
        {"errors": _error_values(errors)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _etag(product: Product) -> str:
    return f'"{product.version}"'


def _response(product: Product, *, response_status: int = status.HTTP_200_OK) -> Response:
    response = Response(ProductSerializer(product).data, status=response_status)
    response["ETag"] = _etag(product)
    return response


def _parse_if_match(request: Request) -> int | Response:
    raw = request.headers.get("If-Match")
    if raw is None:
        return Response(
            {
                "code": "PRODUCT_VERSION_REQUIRED",
                "detail": 'If-Match is required and must contain a quoted positive integer, for example "3".',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    match = re.fullmatch(r'"([1-9][0-9]*)"', raw)
    if match is None:
        return Response(
            {
                "code": "PRODUCT_VERSION_INVALID",
                "detail": 'If-Match must contain a quoted positive integer, for example "3".',
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return int(match.group(1))


def _resolve_filter_concept(*, organization, role: str, value: str, field_name: str):
    identifier = None
    try:
        identifier = uuid.UUID(value)
    except ValueError:
        pass
    identifier_query = Q(code=value)
    if identifier is not None:
        identifier_query |= Q(id=identifier)
    matches = list(
        KnowledgeConcept.objects.filter(
            Q(organization__isnull=True) | Q(organization=organization),
            identifier_query,
            status=KnowledgeConcept.Status.APPROVED,
            concept_type__in=ROLE_CONCEPT_TYPES[role],
        )
        .order_by("id")[:2]
    )
    if len(matches) > 1:
        raise DjangoValidationError(
            {field_name: ["Ambiguous concept filter; use a unique concept UUID or code."]}
        )
    return matches[0] if matches else None


def _concept_filter(
    queryset: QuerySet[Product], *, organization, role: str, concept
) -> QuerySet[Product]:
    if concept is None:
        return queryset.none()
    return queryset.filter(
        concept_links__retired_at__isnull=True,
        concept_links__organization=organization,
        concept_links__role=role,
        concept_links__concept=concept,
        concept_links__concept__status=KnowledgeConcept.Status.APPROVED,
    )


class ProductCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("name_en", "id")


class ProductListView(APIView):
    def get_permissions(self):
        return [(CanReadProducts if self.request.method == "GET" else CanManageProducts)()]

    @extend_schema(
        operation_id="products_list",
        parameters=FILTER_PARAMETERS,
        responses={
            200: ProductListSerializer,
            400: ProductValidationErrorSerializer,
            403: ProductErrorSerializer,
        },
    )
    def get(self, request: Request) -> Response:
        repeated = {
            name: ["Provide this filter at most once."]
            for name in ("type", "material", "application", "status")
            if len(request.query_params.getlist(name)) > 1
        }
        if repeated:
            return _validation_response(repeated)
        filters = ProductFilterSerializer(data=request.query_params)
        if not filters.is_valid():
            return _validation_response(filters.errors)
        queryset = _product_queryset(request.organization)
        values = filters.validated_data
        for name, role in (
            ("type", ProductConceptLink.Role.TYPE),
            ("material", ProductConceptLink.Role.MATERIAL),
            ("application", ProductConceptLink.Role.APPLICATION),
        ):
            if name in values:
                try:
                    concept = _resolve_filter_concept(
                        organization=request.organization,
                        role=role,
                        value=values[name],
                        field_name=name,
                    )
                except DjangoValidationError as error:
                    return _validation_response(error)
                queryset = _concept_filter(
                    queryset,
                    organization=request.organization,
                    role=role,
                    concept=concept,
                )
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        queryset = queryset.distinct().order_by("name_en", "id")
        paginator = ProductCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(ProductSerializer(page, many=True).data)

    @extend_schema(
        operation_id="products_create",
        parameters=[ETAG_RESPONSE_PARAMETER],
        request=ProductCreateSerializer,
        responses={
            201: ProductSerializer,
            400: ProductValidationErrorSerializer,
            403: ProductErrorSerializer,
        },
    )
    def post(self, request: Request) -> Response:
        serializer = ProductCreateSerializer(
            data=request.data,
            context={"organization": request.organization},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        try:
            product = serializer.save()
        except (DjangoValidationError, IntegrityError) as error:
            return _validation_response(error)
        product = _product_queryset(request.organization).get(pk=product.pk)
        return _response(product, response_status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    def get_permissions(self):
        return [(CanReadProducts if self.request.method == "GET" else CanManageProducts)()]

    @extend_schema(
        operation_id="products_retrieve",
        parameters=[ETAG_RESPONSE_PARAMETER],
        responses={200: ProductSerializer, **ERROR_RESPONSES},
    )
    def get(self, request: Request, product_id) -> Response:
        try:
            product = _product_queryset(request.organization).get(pk=product_id)
        except Product.DoesNotExist as error:
            raise Http404 from error
        return _response(product)

    @extend_schema(
        operation_id="products_partial_update",
        parameters=[IF_MATCH_PARAMETER, ETAG_RESPONSE_PARAMETER],
        request=ProductPatchSerializer,
        responses={
            200: ProductSerializer,
            400: PolymorphicProxySerializer(
                component_name="ProductPatchBadRequest",
                serializers=[ProductValidationErrorSerializer, ProductPreconditionErrorSerializer],
                resource_type_field_name=None,
            ),
            **ERROR_RESPONSES,
            409: ProductVersionConflictSerializer,
        },
    )
    def patch(self, request: Request, product_id) -> Response:
        expected_version = _parse_if_match(request)
        if isinstance(expected_version, Response):
            return expected_version
        try:
            with transaction.atomic():
                try:
                    product = Product.objects.select_for_update().get(
                        pk=product_id,
                        organization=request.organization,
                    )
                except Product.DoesNotExist as error:
                    raise Http404 from error
                if product.version != expected_version:
                    raise ProductVersionConflict(product.version)
                serializer = ProductPatchSerializer(
                    product,
                    data=request.data,
                    partial=True,
                    context={"organization": request.organization},
                )
                if not serializer.is_valid():
                    return _validation_response(serializer.errors)
                serializer.save()
        except ProductVersionConflict as error:
            return Response(
                {
                    "code": "PRODUCT_VERSION_CONFLICT",
                    "current_version": error.current_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except (DjangoValidationError, IntegrityError) as error:
            return _validation_response(error)
        product = _product_queryset(request.organization).get(pk=product_id)
        return _response(product)
