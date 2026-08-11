from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Prefetch, QuerySet
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.openapi import bounded_integer_query_parameter
from apps.common.renderers import recoverable_error
from apps.identity.permissions import CanAnalyzeLeads, CanReadLeads, CanReviewLeads
from apps.sources.models import SourceEvidence

from .models import (
    LeadCandidate,
    LeadInsight,
    LeadInsightRequirement,
    LeadReview,
    LeadVersionConflict,
)
from .serializers import (
    LeadAnalyzeAcceptedSerializer,
    LeadAnalyzeRequestSerializer,
    LeadCandidateCreateSerializer,
    LeadCandidateDetailSerializer,
    LeadCandidateListSerializer,
    LeadCandidatePageSerializer,
    LeadCandidateQuerySerializer,
    LeadInsightPageSerializer,
    LeadInsightQuerySerializer,
    LeadInsightSummarySerializer,
    LeadMutationErrorSerializer,
    LeadReadErrorSerializer,
    LeadReviewCreateSerializer,
    LeadReviewResultSerializer,
    LeadValidationErrorSerializer,
)
from .services import (
    LeadAnalysisService,
    LeadIdempotencyConflictError,
    LeadReviewService,
    LeadStateError,
)


PAGE_PARAMETERS = [
    OpenApiParameter("cursor", OpenApiTypes.STR),
    bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
]
LEAD_FILTER_PARAMETERS = [
    OpenApiParameter("status", OpenApiTypes.STR, enum=LeadCandidate.Status.values),
    OpenApiParameter("score_band", OpenApiTypes.STR, enum=LeadInsight.ScoreBand.values),
    OpenApiParameter("minimum_score", OpenApiTypes.INT),
    OpenApiParameter("platform", OpenApiTypes.STR),
    OpenApiParameter("country", OpenApiTypes.STR),
    OpenApiParameter("review_state", OpenApiTypes.STR, enum=["REVIEWED", "UNREVIEWED"]),
    OpenApiParameter("created_after", OpenApiTypes.DATETIME),
    OpenApiParameter("created_before", OpenApiTypes.DATETIME),
    *PAGE_PARAMETERS,
]
READ_ERRORS = {403: LeadReadErrorSerializer, 404: LeadReadErrorSerializer}
MUTATION_ERRORS = {
    400: LeadMutationErrorSerializer,
    403: LeadMutationErrorSerializer,
    404: LeadMutationErrorSerializer,
    409: LeadMutationErrorSerializer,
}


def _error_values(value):
    if isinstance(value, dict):
        return {key: _error_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_error_values(item) for item in value]
    return str(value)


def _validation_response(
    error, *, response_status=status.HTTP_400_BAD_REQUEST, code=None
):
    if isinstance(error, DjangoValidationError):
        values = (
            error.message_dict
            if hasattr(error, "message_dict")
            else {"non_field_errors": error.messages}
        )
    else:
        values = error
    payload = {"errors": _error_values(values)}
    if code:
        payload["code"] = code
    return Response(
        recoverable_error(payload, response_status),
        status=response_status,
    )


def _conflict(error, *, code):
    return Response(
        recoverable_error(
            {"code": code, "detail": str(error)}, status.HTTP_409_CONFLICT
        ),
        status=status.HTTP_409_CONFLICT,
    )


def _require_organization_evidence(organization, evidence_ids) -> None:
    requested = set(evidence_ids)
    visible = SourceEvidence.objects.filter(
        organization=organization,
        pk__in=requested,
    ).count()
    if visible != len(requested):
        raise Http404


class LeadCursorPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


def _candidate_list_queryset(organization) -> QuerySet[LeadCandidate]:
    return LeadCandidate.objects.filter(organization=organization).select_related(
        "latest_insight"
    )


def _candidate_detail_queryset(organization) -> QuerySet[LeadCandidate]:
    requirement_queryset = LeadInsightRequirement.objects.select_related(
        "requirement_concept",
        "capability_concept",
        "capability_knowledge_evidence",
        "source_evidence",
    ).order_by("created_at", "id")
    insight_queryset = (
        LeadInsight.objects.select_related("ai_run__prompt_version", "source_insight")
        .prefetch_related(
            Prefetch(
                "requirements",
                queryset=requirement_queryset,
                to_attr="detail_requirements",
            )
        )
        .order_by("version", "id")
    )
    evidence_queryset = (
        SourceEvidence.objects.filter(organization=organization)
        .order_by("captured_at", "id")
        .distinct()
    )
    review_queryset = LeadReview.objects.select_related("reviewer", "insight").order_by(
        "created_at", "id"
    )
    return (
        LeadCandidate.objects.filter(organization=organization)
        .select_related("latest_insight__ai_run__prompt_version")
        .prefetch_related(
            Prefetch("evidence", queryset=evidence_queryset, to_attr="detail_evidence"),
            Prefetch("insights", queryset=insight_queryset, to_attr="detail_insights"),
            Prefetch("reviews", queryset=review_queryset, to_attr="detail_reviews"),
        )
    )


@extend_schema(tags=["Leads"])
class LeadCandidateListView(APIView):
    def get_permissions(self):
        return [(CanReadLeads if self.request.method == "GET" else CanAnalyzeLeads)()]

    @extend_schema(
        operation_id="lead_candidates_list",
        parameters=LEAD_FILTER_PARAMETERS,
        responses={
            200: LeadCandidatePageSerializer,
            400: LeadValidationErrorSerializer,
            403: LeadReadErrorSerializer,
        },
    )
    def get(self, request):
        repeated = {
            name: ["Provide this filter at most once."]
            for name in LeadCandidateQuerySerializer().fields
            if len(request.query_params.getlist(name)) > 1
        }
        if repeated:
            return _validation_response(repeated)
        serializer = LeadCandidateQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        values = serializer.validated_data
        queryset = _candidate_list_queryset(request.organization)
        if "status" in values:
            queryset = queryset.filter(status=values["status"])
        if "score_band" in values:
            queryset = queryset.filter(latest_insight__score_band=values["score_band"])
        if "minimum_score" in values:
            queryset = queryset.filter(
                latest_insight__score__gte=values["minimum_score"]
            )
        if "platform" in values:
            queryset = queryset.filter(
                evidence_links__evidence__platform__iexact=values["platform"]
            )
        if "country" in values:
            queryset = queryset.filter(country_hint__iexact=values["country"])
        if values.get("review_state") == "REVIEWED":
            queryset = queryset.filter(reviews__isnull=False)
        elif values.get("review_state") == "UNREVIEWED":
            queryset = queryset.filter(reviews__isnull=True)
        if "created_after" in values:
            queryset = queryset.filter(created_at__gte=values["created_after"])
        if "created_before" in values:
            queryset = queryset.filter(created_at__lte=values["created_before"])
        queryset = queryset.distinct().order_by("-created_at", "-id")
        paginator = LeadCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(
            LeadCandidateListSerializer(page, many=True).data
        )

    @extend_schema(
        operation_id="lead_candidates_create",
        request=LeadCandidateCreateSerializer,
        responses={201: LeadCandidateDetailSerializer, **MUTATION_ERRORS},
    )
    def post(self, request):
        serializer = LeadCandidateCreateSerializer(
            data=request.data,
            context={"organization": request.organization, "creator": request.user},
        )
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        _require_organization_evidence(
            request.organization,
            serializer.validated_data["evidence_ids"],
        )
        try:
            candidate = serializer.save()
        except DjangoValidationError as error:
            return _validation_response(error)
        candidate = _candidate_detail_queryset(request.organization).get(
            pk=candidate.pk
        )
        return Response(
            LeadCandidateDetailSerializer(candidate, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["Leads"])
class LeadCandidateDetailView(APIView):
    permission_classes = [CanReadLeads]

    @extend_schema(
        operation_id="lead_candidates_retrieve",
        responses={200: LeadCandidateDetailSerializer, **READ_ERRORS},
    )
    def get(self, request, candidate_id):
        candidate = (
            _candidate_detail_queryset(request.organization)
            .filter(pk=candidate_id)
            .first()
        )
        if candidate is None:
            raise Http404
        return Response(
            LeadCandidateDetailSerializer(candidate, context={"request": request}).data
        )


@extend_schema(tags=["Leads"])
class LeadCandidateAnalyzeView(APIView):
    permission_classes = [CanAnalyzeLeads]

    @extend_schema(
        operation_id="lead_candidates_analyze",
        request=LeadAnalyzeRequestSerializer,
        responses={202: LeadAnalyzeAcceptedSerializer, **MUTATION_ERRORS},
    )
    def post(self, request, candidate_id):
        if not LeadCandidate.objects.filter(
            pk=candidate_id, organization=request.organization
        ).exists():
            raise Http404
        serializer = LeadAnalyzeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        values = serializer.validated_data
        _require_organization_evidence(
            request.organization,
            values["evidence_ids"],
        )
        try:
            job, _prompt = LeadAnalysisService.schedule(
                organization=request.organization,
                candidate=candidate_id,
                evidence_ids=values["evidence_ids"],
                expected_version=values["expected_version"],
                idempotency_key=values["idempotency_key"],
                actor=request.user,
            )
        except LeadIdempotencyConflictError as error:
            return _conflict(error, code="idempotency_conflict")
        except LeadVersionConflict as error:
            return _conflict(error, code="version_conflict")
        except LeadStateError as error:
            return _conflict(error, code="lead_state_conflict")
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(
            {
                "job_id": job.id,
                "lead_candidate_id": candidate_id,
                "status": job.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


@extend_schema(tags=["Leads"])
class LeadInsightListView(APIView):
    permission_classes = [CanReadLeads]

    @extend_schema(
        operation_id="lead_insights_list",
        parameters=[
            OpenApiParameter("candidate_id", OpenApiTypes.UUID),
            *PAGE_PARAMETERS,
        ],
        responses={
            200: LeadInsightPageSerializer,
            400: LeadValidationErrorSerializer,
            403: LeadReadErrorSerializer,
        },
    )
    def get(self, request):
        repeated = {
            name: ["Provide this filter at most once."]
            for name in LeadInsightQuerySerializer().fields
            if len(request.query_params.getlist(name)) > 1
        }
        if repeated:
            return _validation_response(repeated)
        serializer = LeadInsightQuerySerializer(data=request.query_params)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        queryset = LeadInsight.objects.filter(
            organization=request.organization
        ).select_related("ai_run__prompt_version", "source_insight")
        if "candidate_id" in serializer.validated_data:
            queryset = queryset.filter(
                candidate_id=serializer.validated_data["candidate_id"]
            )
        queryset = queryset.order_by("-created_at", "-id")
        paginator = LeadCursorPagination()
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except NotFound:
            return _validation_response({"cursor": ["Invalid or expired cursor."]})
        return paginator.get_paginated_response(
            LeadInsightSummarySerializer(page, many=True).data
        )


@extend_schema(tags=["Leads"])
class LeadReviewCreateView(APIView):
    permission_classes = [CanReviewLeads]

    @extend_schema(
        operation_id="lead_reviews_create",
        request=LeadReviewCreateSerializer,
        responses={201: LeadReviewResultSerializer, **MUTATION_ERRORS},
    )
    def post(self, request):
        serializer = LeadReviewCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return _validation_response(serializer.errors)
        values = serializer.validated_data
        candidate = LeadCandidate.objects.filter(
            pk=values["candidate_id"], organization=request.organization
        ).first()
        if candidate is None:
            raise Http404
        try:
            result = LeadReviewService.apply(
                organization=request.organization,
                candidate=candidate,
                action=values["action"],
                expected_version=values["expected_version"],
                correction=values.get("correction"),
                reason=values["reason"],
                reviewer=request.user,
                idempotency_key=values["idempotency_key"],
            )
        except LeadIdempotencyConflictError as error:
            return _conflict(error, code="idempotency_conflict")
        except LeadVersionConflict as error:
            return _conflict(error, code="version_conflict")
        except LeadStateError as error:
            return _conflict(error, code="lead_state_conflict")
        except DjangoValidationError as error:
            return _validation_response(error)
        return Response(
            {
                "review_id": result.review.id,
                "lead_candidate_id": result.candidate.id,
                "candidate_status": result.candidate.status,
                "candidate_version": result.candidate.version,
                "insight_id": result.insight.id if result.insight else None,
                "insight_version": (result.insight.version if result.insight else None),
            },
            status=status.HTTP_201_CREATED,
        )
