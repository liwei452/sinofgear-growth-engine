from django.db import transaction
import hashlib
import json
from django.db.models import Exists, OuterRef
from django.http import Http404
from drf_spectacular.utils import (
    OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view,
)
from rest_framework import status
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai.models import PromptVersion
from apps.ai.runtime import product_ai_status
from apps.campaigns.models import ContentBrief, ContentBriefPlatform
from apps.campaigns.services import build_content_generation_input
from django.core.exceptions import ValidationError
from apps.common.openapi import bounded_integer_query_parameter
from apps.identity.permissions import CanManageContent, CanReadContent, CanReviewContent
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.platforms.models import Platform

from .models import (
    ContentRecommendation, ContentRecommendationOption, MasterContent, PlatformContent,
)
from .recommendations import (
    ContentRecommendationError, build_recommendation_input,
    select_recommendation_option,
)
from .serializers import (
    EmptySerializer, JobAcceptedSerializer, MasterContentSerializer,
    MasterRevisionSerializer, PlatformContentSerializer,
    PlatformGenerationSerializer, PlatformRevisionSerializer, ReviewSerializer,
    ContentFilterSerializer,
    ContentRecommendationSerializer, RecommendationAcceptedSerializer,
    RecommendationSelectionSerializer,
)
from .services import (
    ContentStateError, create_master_revision, create_platform_content,
    create_platform_revision, transition_content, content_is_consistent,
)
from .tasks import generate_content_recommendations_job, generate_master_content_job


class ContentPagination(CursorPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 50
    ordering = ("-created_at", "-id")


@extend_schema(tags=["ContentRecommendations"])
class ContentRecommendationListCreateView(APIView):
    def get_permissions(self):
        return [CanManageContent()] if self.request.method == "POST" else [CanReadContent()]

    @extend_schema(responses={200: ContentRecommendationSerializer(many=True)})
    def get(self, request):
        rows = ContentRecommendation.objects.filter(
            organization=request.organization
        ).exclude(status=ContentRecommendation.Status.ARCHIVED).prefetch_related(
            "options"
        ).order_by("-created_at", "-id")[:50]
        return Response({"results": ContentRecommendationSerializer(rows, many=True).data})

    @extend_schema(request=EmptySerializer, responses={202: RecommendationAcceptedSerializer})
    def post(self, request):
        serializer = EmptySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        provider_status = product_ai_status()
        if provider_status["mode"] == "CONFIGURATION_REQUIRED":
            return Response({
                "code": "CONFIGURATION_REQUIRED",
                "message": "AI provider is not configured.",
                "recovery_action": "Configure the product AI provider in settings.",
            }, status=status.HTTP_409_CONFLICT)
        try:
            snapshot = build_recommendation_input(request.organization.id).to_dict()
        except ContentRecommendationError as exc:
            return Response({
                "code": "RECOMMENDATION_INPUT_REQUIRED",
                "message": str(exc),
                "recovery_action": "Complete the missing verified product or market information.",
            }, status=status.HTTP_409_CONFLICT)
        prompt = PromptVersion.objects.filter(
            purpose="CONTENT_RECOMMEND", status=PromptVersion.Status.PUBLISHED
        ).order_by("-version").first()
        if prompt is None:
            return _error(
                ContentStateError("Published recommendation prompt is unavailable."),
                code="RECOMMENDATION_PROMPT_REQUIRED",
            )
        digest = hashlib.sha256(json.dumps(
            snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()[:32]
        idempotency_key = f"recommend:{prompt.id}:{digest}"
        existing_job = Job.objects.filter(
            organization=request.organization,
            type=Job.Type.CONTENT_RECOMMEND,
            idempotency_key=idempotency_key,
        ).first()
        if existing_job is not None:
            recommendation = ContentRecommendation.objects.get(job=existing_job)
        else:
            job = JobService.create(
                organization=request.organization,
                job_type=Job.Type.CONTENT_RECOMMEND,
                input_snapshot=snapshot,
                idempotency_key=idempotency_key,
                created_by=request.user,
            )
            recommendation = ContentRecommendation.objects.create(
                organization=request.organization,
                job=job,
                input_snapshot=snapshot,
                provider_mode=(
                    ContentRecommendation.ProviderMode.FAKE_OFFLINE
                    if provider_status["mode"] == "FAKE_OFFLINE"
                    else ContentRecommendation.ProviderMode.CONFIGURED_AI
                ),
                created_by=request.user,
            )
            transaction.on_commit(lambda: generate_content_recommendations_job.delay(
                str(job.id), str(prompt.id)
            ))
            existing_job = job
        return Response({
            "recommendation_id": recommendation.id,
            "job_id": existing_job.id,
            "status": existing_job.status,
            "generation_mode": recommendation.provider_mode,
            "generation_label": (
                "Fake / 离线演示推荐"
                if recommendation.provider_mode == ContentRecommendation.ProviderMode.FAKE_OFFLINE
                else "已配置真实 AI 推荐"
            ),
        }, status=202)


@extend_schema(tags=["ContentRecommendations"])
class ContentRecommendationDetailView(APIView):
    permission_classes = [CanReadContent]

    @extend_schema(responses={200: ContentRecommendationSerializer})
    def get(self, request, recommendation_id):
        try:
            recommendation = ContentRecommendation.objects.prefetch_related("options").get(
                pk=recommendation_id, organization=request.organization
            )
        except ContentRecommendation.DoesNotExist as exc:
            raise Http404 from exc
        return Response(ContentRecommendationSerializer(recommendation).data)


@extend_schema(tags=["ContentRecommendations"])
class ContentRecommendationSelectView(APIView):
    permission_classes = [CanManageContent]

    @extend_schema(request=EmptySerializer, responses={200: RecommendationSelectionSerializer})
    def post(self, request, recommendation_id, option_id):
        serializer = EmptySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        try:
            recommendation = ContentRecommendation.objects.get(
                pk=recommendation_id, organization=request.organization
            )
            option = ContentRecommendationOption.objects.get(
                pk=option_id, recommendation=recommendation,
                organization=request.organization,
            )
            brief = select_recommendation_option(
                recommendation=recommendation, option=option, actor=request.user
            )
        except (ContentRecommendation.DoesNotExist, ContentRecommendationOption.DoesNotExist) as exc:
            raise Http404 from exc
        except (ContentRecommendationError, ValidationError) as exc:
            return _error(exc, code="RECOMMENDATION_SELECTION_INVALID")
        return Response({
            "recommendation_id": recommendation.id,
            "option_id": option.id,
            "brief_id": brief.id,
            "brief_status": brief.status,
        })


def _generation_job_response(job, provider_status):
    latest_run = job.ai_runs.order_by("-job_attempt", "-created_at").first()
    fake_mode = (
        latest_run.provider == "fake"
        if latest_run is not None
        else provider_status["mode"] == "FAKE_OFFLINE"
    )
    return Response({
        "job_id": job.id,
        "status": job.status,
        "generation_mode": "FAKE_OFFLINE" if fake_mode else "CONFIGURED_AI",
        "generation_label": "Fake / 离线演示生成" if fake_mode else "已配置真实 AI 生成",
    }, status=202)


def _with_current_head(queryset, model):
    successors = model.objects.filter(
        organization_id=OuterRef("organization_id"),
        lineage_id=OuterRef("lineage_id"),
        previous_version_id=OuterRef("pk"),
    )
    return queryset.annotate(_is_current_head=~Exists(successors))


def _object(model, organization, pk):
    try:
        queryset = model.objects.select_related(
            *("brief", "generation_job", "ai_run", "previous_version")
            if model is MasterContent
            else (
                "master_content__brief", "master_content__generation_job",
                "master_content__ai_run", "master_content__previous_version",
                "platform", "previous_version", "growth_channel_package",
            )
        )
        if model is PlatformContent:
            queryset = queryset.annotate(
                _selected_platform=Exists(
                    ContentBriefPlatform.objects.filter(
                        brief_id=OuterRef("master_content__brief_id"),
                        platform_id=OuterRef("platform_id"),
                    )
                )
            )
        content = _with_current_head(queryset, model).get(
            pk=pk, organization=organization
        )
        if not content_is_consistent(content):
            raise Http404
        return content
    except (model.DoesNotExist, ValueError) as exc:
        raise Http404 from exc


def _error(exc, code="invalid_content_transition"):
    return Response(
        {"code": code, "message": str(exc), "recovery_action": "Refresh and retry."},
        status=status.HTTP_409_CONFLICT,
    )


class ContentListView(APIView):
    permission_classes = [CanReadContent]
    model = MasterContent
    serializer = MasterContentSerializer
    serializer_class = MasterContentSerializer

    @extend_schema(parameters=[
        OpenApiParameter("status", OpenApiTypes.STR),
        bounded_integer_query_parameter("page_size", minimum=1, maximum=50),
    ])
    def get(self, request):
        queryset = self.model.objects.filter(organization=request.organization)
        queryset = _with_current_head(queryset, self.model)
        if self.model is MasterContent:
            queryset = queryset.select_related(
                "brief", "generation_job", "ai_run", "previous_version"
            )
        else:
            queryset = queryset.select_related(
                "master_content__brief", "master_content__generation_job",
                "master_content__ai_run", "master_content__previous_version",
                "platform", "previous_version", "growth_channel_package",
            ).annotate(
                _selected_platform=Exists(
                    ContentBriefPlatform.objects.filter(
                        brief_id=OuterRef("master_content__brief_id"),
                        platform_id=OuterRef("platform_id"),
                    )
                )
            )
        repeated = {
            name: ["Provide this filter at most once."]
            for name in request.query_params
            if len(request.query_params.getlist(name)) > 1
        }
        serializer = ContentFilterSerializer(data=request.query_params)
        if repeated or not serializer.is_valid():
            errors = {**serializer.errors, **repeated}
            return Response({"errors": errors}, status=400)
        values = serializer.validated_data
        if "status" in values and values["status"] not in self.model.Status.values:
            return Response(
                {"errors": {"status": ["Select a valid choice."]}}, status=400
            )
        for key in ("status", "version"):
            if key in values:
                queryset = queryset.filter(**{key: values[key]})
        if "lineage" in values:
            queryset = queryset.filter(lineage_id=values["lineage"])
        prefix = "" if self.model is MasterContent else "master_content__"
        if "brief" in values:
            queryset = queryset.filter(**{f"{prefix}brief_id": values["brief"]})
        if "campaign" in values:
            queryset = queryset.filter(**{f"{prefix}brief__campaign_id": values["campaign"]})
        if "product" in values:
            queryset = queryset.filter(**{f"{prefix}brief__product_links__product_id": values["product"]})
        if "platform" in values:
            if self.model is PlatformContent:
                queryset = queryset.filter(platform_id=values["platform"])
            else:
                queryset = queryset.filter(brief__platform_links__platform_id=values["platform"])
        queryset = queryset.distinct()
        paginator = ContentPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        safe_page = [content for content in page if content_is_consistent(content)]
        return paginator.get_paginated_response(self.serializer(safe_page, many=True).data)


@extend_schema_view(get=extend_schema(operation_id="master_contents_list", tags=["MasterContents"]))
class MasterListView(ContentListView):
    pass


@extend_schema_view(get=extend_schema(operation_id="platform_contents_list", tags=["PlatformContents"]))
class PlatformListView(ContentListView):
    model = PlatformContent
    serializer = PlatformContentSerializer
    serializer_class = PlatformContentSerializer


class ContentDetailView(APIView):
    permission_classes = [CanReadContent]
    model = MasterContent
    serializer = MasterContentSerializer
    serializer_class = MasterContentSerializer

    def get(self, request, content_id):
        return Response(self.serializer(_object(self.model, request.organization, content_id)).data)


@extend_schema_view(get=extend_schema(operation_id="master_contents_retrieve", tags=["MasterContents"]))
class MasterDetailView(ContentDetailView):
    pass


@extend_schema_view(get=extend_schema(operation_id="platform_contents_retrieve", tags=["PlatformContents"]))
class PlatformDetailView(ContentDetailView):
    model = PlatformContent
    serializer = PlatformContentSerializer
    serializer_class = PlatformContentSerializer


@extend_schema(tags=["MasterContents"])
class MasterRevisionView(APIView):
    permission_classes = [CanManageContent]
    serializer_class = MasterRevisionSerializer

    @extend_schema(request=MasterRevisionSerializer, responses={201: MasterContentSerializer})
    def post(self, request, content_id):
        serializer = MasterRevisionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        source = _object(MasterContent, request.organization, content_id)
        try:
            revision = create_master_revision(
                source, actor=request.user, payload=serializer.validated_data["payload"]
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(MasterContentSerializer(revision).data, status=201)


@extend_schema(tags=["PlatformContents"])
class PlatformRevisionView(APIView):
    permission_classes = [CanManageContent]
    serializer_class = PlatformRevisionSerializer

    @extend_schema(request=PlatformRevisionSerializer, responses={201: PlatformContentSerializer})
    def post(self, request, content_id):
        serializer = PlatformRevisionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        source = _object(PlatformContent, request.organization, content_id)
        try:
            revision = create_platform_revision(
                source, actor=request.user, payload=serializer.validated_data["payload"]
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(PlatformContentSerializer(revision).data, status=201)


class ContentActionView(APIView):
    permission_classes = [CanReviewContent]
    model = MasterContent
    serializer = MasterContentSerializer
    action = ""
    serializer_class = ReviewSerializer

    @extend_schema(request=ReviewSerializer)
    def post(self, request, content_id):
        serializer = ReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        content = _object(self.model, request.organization, content_id)
        try:
            content = transition_content(
                content, action=self.action, actor=request.user,
                comment=serializer.validated_data["comment"],
            )
        except ContentStateError as exc:
            return _error(exc)
        return Response(self.serializer(content).data)


@extend_schema(tags=["MasterContents"])
class MasterApproveView(ContentActionView):
    action = "APPROVE"


@extend_schema(tags=["MasterContents"])
class MasterRejectView(ContentActionView):
    action = "REJECT"


@extend_schema(tags=["MasterContents"])
class MasterArchiveView(ContentActionView):
    action = "ARCHIVE"


@extend_schema(tags=["MasterContents"])
class MasterSubmitView(ContentActionView):
    permission_classes = [CanManageContent]
    action = "SUBMIT"


class PlatformActionView(ContentActionView):
    model = PlatformContent
    serializer = PlatformContentSerializer


@extend_schema(tags=["PlatformContents"])
class PlatformApproveView(PlatformActionView):
    action = "APPROVE"


@extend_schema(tags=["PlatformContents"])
class PlatformRejectView(PlatformActionView):
    action = "REJECT"


@extend_schema(tags=["PlatformContents"])
class PlatformArchiveView(PlatformActionView):
    action = "ARCHIVE"


@extend_schema(tags=["PlatformContents"])
class PlatformSubmitView(PlatformActionView):
    permission_classes = [CanManageContent]
    action = "SUBMIT"


@extend_schema(tags=["MasterContents"])
class GeneratePlatformView(APIView):
    permission_classes = [CanManageContent]

    @extend_schema(request=PlatformGenerationSerializer, responses={201: PlatformContentSerializer})
    def post(self, request, content_id):
        serializer = PlatformGenerationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        master = _object(MasterContent, request.organization, content_id)
        try:
            platform = Platform.objects.get(pk=serializer.validated_data["platform_id"])
            content = create_platform_content(master, platform=platform, actor=request.user)
        except Platform.DoesNotExist as exc:
            raise Http404 from exc
        except ContentStateError as exc:
            return _error(exc)
        return Response(PlatformContentSerializer(content).data, status=201)


@extend_schema(tags=["ContentBriefs"])
class GenerateMasterView(APIView):
    permission_classes = [CanManageContent]

    @extend_schema(request=EmptySerializer, responses={202: JobAcceptedSerializer})
    def post(self, request, brief_id):
        serializer = EmptySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"errors": serializer.errors}, status=400)
        try:
            brief = ContentBrief.objects.get(pk=brief_id, organization=request.organization)
        except ContentBrief.DoesNotExist as exc:
            raise Http404 from exc
        if brief.status != ContentBrief.Status.READY:
            return _error(ContentStateError("Content brief must be READY."))
        provider_status = product_ai_status()
        if provider_status["mode"] == "CONFIGURATION_REQUIRED":
            return Response({
                "code": "CONFIGURATION_REQUIRED",
                "message": "DeepSeek API key is not configured.",
                "recovery_action": "Configure the server environment before using real AI.",
            }, status=status.HTTP_409_CONFLICT)
        prompt = PromptVersion.objects.filter(
            purpose="CONTENT_GENERATE", status=PromptVersion.Status.PUBLISHED
        ).order_by("-version").first()
        if prompt is None:
            return _error(ContentStateError("Published generation prompt is unavailable."))
        idempotency_key = f"master:{brief.id}:{brief.version}:{prompt.id}"
        existing_job = Job.objects.filter(
            organization=request.organization,
            type=Job.Type.CONTENT_GENERATE,
            idempotency_key=idempotency_key,
        ).first()
        if existing_job is not None:
            return _generation_job_response(existing_job, provider_status)
        snapshot = build_content_generation_input(brief.id).to_dict()
        job = JobService.create(
            organization=request.organization,
            job_type=Job.Type.CONTENT_GENERATE,
            input_snapshot=snapshot,
            idempotency_key=idempotency_key,
            created_by=request.user,
        )
        transaction.on_commit(
            lambda: generate_master_content_job.delay(str(job.id), str(prompt.id))
        )
        return _generation_job_response(job, provider_status)
